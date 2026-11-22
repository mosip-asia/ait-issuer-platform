/*
 * This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0. If a copy of the MPL was not
 * distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.
 *
 * Copied from mosip/mimoto v0.21.0, src/main/java/io/mosip/mimoto/service/CredentialPDFGeneratorService.java: the
 * HTML path of generatePdfForVerifiableCredential (getPdfResourceFromVcProperties, extractFace, formatValue,
 * renderVCInCredentialTemplate, constructQRCode) and Utilities.encodeToString. Changed: no Spring; the template, the
 * claims and the issuer's metadata are passed in instead of fetched; the QR holds placeholder text, as no credential
 * is signed; logoUrl comes from the credential file's display entry, as no issuers list is read. Left out: the SVG
 * path, SD-JWT disclosures (an ldp_vc credential has none) and the data-share and OVP QR codes.
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
import org.apache.velocity.VelocityContext;
import org.apache.velocity.app.Velocity;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.StringWriter;
import java.util.*;

public class CredentialPDFGeneratorService {

    private record SelectedFace(String key, String face) {}

    // Mimoto's settings: its defaults, and deploy/base/mimoto-default.properties for the QR size.
    private final String faceImageLookupKeys = "image,face,photo,picture,portrait";
    private final boolean maskDisclosures = true;
    private final Integer qrCodeHeight = 400;
    private final Integer qrCodeWidth = 400;
    // What Mimoto's download endpoint passes when the Wallet sends no vcStorageExpiryLimitInTimes.
    private final String credentialValidity = "-1";
    private static final String PLACEHOLDER_QR_DATA = "VC Lab preview: the Wallet's QR code holds the credential";

    /**
     * The PDF Mimoto prints for an ldp_vc credential with these claims, issued under this metadata. A non-null
     * backgroundImage replaces display[0].background_image.uri.
     */
    public byte[] generatePdf(String credentialTemplate, Map<String, Object> credentialProperties,
                              CredentialsSupportedResponse credentialsSupportedResponse, String backgroundImage,
                              String locale) throws IOException, WriterException {
        LinkedHashMap<String, Map<CredentialIssuerDisplayResponse, Object>> displayProperties = new LinkedHashMap<>();
        credentialProperties.forEach((key, value) -> {
            CredentialIssuerDisplayResponse display = new CredentialIssuerDisplayResponse();
            display.setName(key);
            display.setLocale("en");
            displayProperties.put(key, Map.of(display, value));
        });
        Map<String, Object> data = getPdfResourceFromVcProperties(displayProperties, credentialsSupportedResponse,
                credentialProperties);
        if (backgroundImage != null) {
            data.put("backgroundImage", backgroundImage);
        }
        return renderVCInCredentialTemplate(data, credentialTemplate);
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
        String logoUrl = firstDisplay != null && firstDisplay.getLogo() != null ? firstDisplay.getLogo().getUrl() : null;

        SelectedFace selectedFace = extractFace(credentialSubject);
        String face = selectedFace.face();
        String selectedFaceKey = selectedFace.key();

        LinkedHashMap<String, String> disclosuresProps = new LinkedHashMap<>();
        displayProperties.forEach((key, valueMap) -> {
            boolean isFaceKey = selectedFaceKey != null && key.trim().equals(selectedFaceKey);

            valueMap.forEach((display, val) -> {
                String displayName = display.getName();
                String strVal = formatValue(val);
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
        data.put("logoUrl", logoUrl != null ? logoUrl : "");
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

    private String formatValue(Object val) {
        return val != null ? val.toString() : "";
    }

    private byte[] renderVCInCredentialTemplate(Map<String, Object> data, String credentialTemplate) {
        Properties props = new Properties();
        props.setProperty("resource.loader", "class");
        props.setProperty("class.resource.loader.class", "org.apache.velocity.runtime.resource.loader.ClasspathResourceLoader");
        Velocity.init(props);
        VelocityContext velocityContext = new VelocityContext(data);

        StringWriter writer = new StringWriter();
        Velocity.evaluate(velocityContext, writer, "Credential Template", credentialTemplate);

        String mergedHtml = writer.toString();
        ByteArrayOutputStream outputStream = new ByteArrayOutputStream();

        PdfWriter pdfwriter = new PdfWriter(outputStream);
        DefaultFontProvider defaultFont = new DefaultFontProvider(true, false, false);
        ConverterProperties converterProperties = new ConverterProperties();
        converterProperties.setFontProvider(defaultFont);
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
