/*
 * This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0. If a copy of the MPL was not
 * distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.
 *
 * Copied from mosip/mimoto v0.21.0, src/main/java/io/mosip/mimoto/service/CredentialPDFGeneratorService.java: the
 * HTML path of generatePdfForVerifiableCredential (getPdfResourceFromVcProperties, extractFace, formatValue,
 * renderVCInCredentialTemplate, constructQRCode) and Utilities.encodeToString, with ait-mimoto's two changes
 * (src/mimoto/CredentialPDFGeneratorService.java: templates also get $credentialSubject, and Velocity runs with
 * SecureUberspector). Changed: no Spring; the template, the claims and the issuer's metadata are passed in instead of
 * fetched; the QR holds placeholder text, as no credential is signed; logoUrl is empty, as no issuers list is read; a
 * new Velocity engine renders each print; renderVCInCredentialTemplate is split into the Velocity step
 * (generateHtml) and the iText step (toPdf); iText loads addresses through the caller's resource retriever, not
 * the network. Left out: the SVG path, SD-JWT disclosures (an ldp_vc credential has none) and the data-share and OVP
 * QR codes.
 */
package asia.mosip.renderer.mimoto;

import asia.mosip.renderer.mimoto.Wellknown.CredentialIssuerDisplayResponse;
import asia.mosip.renderer.mimoto.Wellknown.CredentialSupportedDisplayResponse;
import asia.mosip.renderer.mimoto.Wellknown.CredentialsSupportedResponse;
import com.google.zxing.BarcodeFormat;
import com.google.zxing.WriterException;
import com.google.zxing.client.j2se.MatrixToImageWriter;
import com.google.zxing.common.BitMatrix;
import com.google.zxing.qrcode.QRCodeWriter;
import com.itextpdf.html2pdf.ConverterProperties;
import com.itextpdf.html2pdf.HtmlConverter;
import com.itextpdf.html2pdf.resolver.font.DefaultFontProvider;
import com.itextpdf.kernel.pdf.PdfWriter;
import com.itextpdf.styledxmlparser.resolver.resource.IResourceRetriever;
import org.apache.velocity.VelocityContext;
import org.apache.velocity.app.VelocityEngine;
import org.apache.velocity.util.introspection.SecureUberspector;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.io.StringWriter;
import java.util.*;

public class CredentialPDFGeneratorService {

    private record SelectedFace(String key, String face) {}

    static {
        // Changed: ImageIO.write keeps its stream cache in memory. By default it writes a temporary file, which the
        // renderer's read-only filesystem refuses (and which would put a QR code on disk).
        ImageIO.setUseCache(false);
    }

    // Mimoto's settings: its defaults, and deploy/base/mimoto-default.properties for the QR size.
    private final String faceImageLookupKeys = "image,face,photo,picture,portrait";
    private final boolean maskDisclosures = true;
    private final Integer qrCodeHeight = 400;
    private final Integer qrCodeWidth = 400;
    // What Mimoto's download endpoint passes when the Wallet sends no vcStorageExpiryLimitInTimes.
    private final String credentialValidity = "-1";
    private final LdpVcCredentialFormatHandler processor = new LdpVcCredentialFormatHandler();
    private static final String PLACEHOLDER_QR_DATA = "VC Lab preview: the Wallet's QR code holds the credential";

    /**
     * The HTML ait-mimoto hands iText for an ldp_vc credential with these claims, issued under this metadata: the
     * template evaluated by Velocity. A non-null backgroundImage replaces display[0].background_image.uri.
     */
    public String generateHtml(String credentialTemplate, Map<String, Object> credentialProperties,
                               CredentialsSupportedResponse credentialsSupportedResponse, String backgroundImage,
                               String locale) throws WriterException {
        LinkedHashMap<String, Map<CredentialIssuerDisplayResponse, Object>> displayProperties =
                processor.loadDisplayPropertiesFromWellknown(credentialProperties, credentialsSupportedResponse, locale);
        Map<String, Object> data = getPdfResourceFromVcProperties(displayProperties, credentialsSupportedResponse,
                credentialProperties);
        // ait-mimoto: the only change to upstream v0.21.0. Templates also get the claims as received, unflattened.
        data.put("credentialSubject", credentialProperties);
        if (backgroundImage != null) {
            data.put("backgroundImage", backgroundImage);
        }
        return evaluate(data, credentialTemplate);
    }

    private Map<String, Object> getPdfResourceFromVcProperties(
            LinkedHashMap<String, Map<CredentialIssuerDisplayResponse, Object>> displayProperties,
            CredentialsSupportedResponse credentialsSupportedResponse,
            Map<String, Object> credentialSubject) throws WriterException {

        Map<String, Object> data = new HashMap<>();
        LinkedHashMap<String, Object> rowProperties = new LinkedHashMap<>();

        CredentialSupportedDisplayResponse firstDisplay = Optional.ofNullable(credentialsSupportedResponse.getDisplay())
                .filter(list -> !list.isEmpty())
                .map(List::getFirst)
                .orElse(null);

        String backgroundColor = firstDisplay != null ? firstDisplay.getBackgroundColor() : null;
        String backgroundImage = firstDisplay != null && firstDisplay.getBackgroundImage() != null
                ? firstDisplay.getBackgroundImage().getUri()
                : null;
        String textColor = firstDisplay != null ? firstDisplay.getTextColor() : null;
        String credentialSupportedType = firstDisplay != null ? firstDisplay.getName() : null;

        SelectedFace selectedFace = extractFace(credentialSubject);
        String face = selectedFace.face();
        String selectedFaceKey = selectedFace.key();

        LinkedHashMap<String, String> disclosuresProps = new LinkedHashMap<>();
        displayProperties.forEach((key, valueMap) -> {
            boolean isFaceKey = selectedFaceKey != null && key.trim().equals(selectedFaceKey);

            valueMap.forEach((display, val) -> {
                String displayName = display.getName();
                String locale = display.getLocale();
                String strVal = formatValue(val, locale);
                if (!isFaceKey && displayName != null) {
                    rowProperties.put(key, Map.of(displayName, strVal));
                }
            });
        });

        String qrCodeImage = constructQRCode(PLACEHOLDER_QR_DATA);

        data.put("isMaskedOn", maskDisclosures);
        data.put("isSdJwtWithDisclosures", false);
        data.put("qrCodeImage", qrCodeImage);
        data.put("credentialValidity", credentialValidity);
        data.put("logoUrl", "");  // no issuers list is read: the logo belongs in the Background
        data.put("rowProperties", rowProperties);
        data.put("disclosures", disclosuresProps);
        data.put("textColor", textColor);
        data.put("backgroundColor", backgroundColor);
        data.put("backgroundImage", backgroundImage);
        data.put("titleName", credentialSupportedType);
        data.put("face", face);
        return data;
    }

    private SelectedFace extractFace(Map<String, Object> credentialSubject) {
        // handling face extraction based on configured keys
        List<String> faceKeys = Arrays.asList(faceImageLookupKeys.split(","));
        for (String faceKey : faceKeys) {
            String trimmedKey = faceKey.trim();
            Object faceValue = credentialSubject.get(trimmedKey);
            if (faceValue != null && !faceValue.toString().isEmpty()) {
                // Return the trimmedKey directly
                return new SelectedFace(trimmedKey, faceValue.toString());
            }
        }
        return new SelectedFace(null, null);
    }

    private String formatValue(Object val, String locale) {
        if (val instanceof Map) {
            return Optional.ofNullable(((Map<?, ?>) val).get("value")).map(Object::toString).orElse("");
        } else if (val instanceof List) {
            List<?> list = (List<?>) val;
            if (list.isEmpty()) return "";
            if (list.getFirst() instanceof String) {
                return String.join(", ", (List<String>) list);
            } else if (list.getFirst() instanceof Map<?, ?>) {
                return list.stream()
                        .filter(Objects::nonNull)
                        .map(item -> (Map<?, ?>) item)
                        .filter(m -> {
                            Object lang = m.get("language");  // Safely get language
                            return lang != null && LocaleUtils.matchesLocale(lang.toString(), locale);
                        })
                        .map(m -> {
                            Object value = m.get("value");  // Safely get value
                            return value != null ? value.toString() : null;
                        })
                        .filter(Objects::nonNull)
                        .findFirst()
                        .orElse("");
            }
        }
        return val != null ? val.toString() : "";
    }

    // renderVCInCredentialTemplate, split in two so the HTML iText receives can be handed out as it is.
    private String evaluate(Map<String, Object> data, String credentialTemplate) {
        Properties props = new Properties();
        props.setProperty("resource.loader", "class");
        props.setProperty("class.resource.loader.class", "org.apache.velocity.runtime.resource.loader.ClasspathResourceLoader");
        // ait-mimoto's second change: a template can't call methods on Java's reflection and system classes. A
        // second layer only, as Velocity 1.7's list has a known bypass (CVE-2020-13936); the container is the boundary.
        props.setProperty("runtime.introspector.uberspect", SecureUberspector.class.getName());
        // Changed: a new engine per print, with the properties Mimoto passes to the Velocity singleton. A macro a
        // template defines stays in the singleton for good, so each preview would otherwise depend on the ones
        // before it; this gives every preview Mimoto's first print after a restart.
        VelocityEngine velocity = new VelocityEngine(props);
        VelocityContext velocityContext = new VelocityContext(data);

        StringWriter writer = new StringWriter();
        velocity.evaluate(velocityContext, writer, "Credential Template", credentialTemplate);
        return writer.toString();
    }

    /**
     * The PDF iText makes of the evaluated HTML, as Mimoto converts it. Changed: iText loads every address through
     * {@code resources}, where Mimoto's iText fetches it.
     */
    public byte[] toPdf(String mergedHtml, IResourceRetriever resources) {
        ByteArrayOutputStream outputStream = new ByteArrayOutputStream();

        PdfWriter pdfwriter = new PdfWriter(outputStream);
        DefaultFontProvider defaultFont = new DefaultFontProvider(true, false, false);
        ConverterProperties converterProperties = new ConverterProperties();
        converterProperties.setFontProvider(defaultFont);
        converterProperties.setResourceRetriever(resources);
        HtmlConverter.convertToPdf(mergedHtml, pdfwriter, converterProperties);
        return outputStream.toByteArray();
    }

    private String constructQRCode(String qrData) throws WriterException {
        QRCodeWriter qrCodeWriter = new QRCodeWriter();
        BitMatrix bitMatrix = qrCodeWriter.encode(qrData, BarcodeFormat.QR_CODE, qrCodeWidth, qrCodeHeight);
        BufferedImage qrImage = MatrixToImageWriter.toBufferedImage(bitMatrix);
        return encodeToString(qrImage, "png");
    }

    // Utilities.encodeToString
    private static String encodeToString(BufferedImage image, String type) {
        String imageString = null;
        ByteArrayOutputStream bos = new ByteArrayOutputStream();

        try {
            ImageIO.write(image, type, bos);
            byte[] imageBytes = bos.toByteArray();
            Base64.Encoder encoder = Base64.getEncoder();
            imageString = encoder.encodeToString(imageBytes);
            bos.close();
        } catch (Exception e) {
            e.printStackTrace();
        }
        return imageString;
    }
}
