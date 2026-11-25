package asia.mosip.renderer;

import com.itextpdf.styledxmlparser.resolver.resource.IResourceRetriever;
import com.itextpdf.styledxmlparser.resolver.resource.UriResolver;
import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.net.MalformedURLException;
import java.net.URL;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.SequencedSet;

/**
 * All iText may load while it prints: the set's files, at their VDR address. iText decodes data: URIs itself and
 * asks this for every other address (an image, a font, a stylesheet, an SVG's own references). An address under
 * {@link #VDR_TEMPLATES} whose file name is one of the set's files is that file, whatever the folders between.
 * Every other address is refused and noted in {@link #refused()}: iText logs a resource it can't load and prints
 * without it, so the caller fails the print instead, as the Wallet would print what the preview left out.
 */
final class SetFiles implements IResourceRetriever {

    static final String VDR_TEMPLATES = "http://vdr.localhost/templates/";

    // Where iText resolves an empty address, src="": its base, the working directory, as no base URI is set (as in
    // Mimoto). The Wallet loads nothing there either, so the demo template's <img src="$logoUrl">, with $logoUrl
    // empty, draws no image and is not refused.
    private static final String EMPTY_ADDRESS = emptyAddress();

    private final Map<String, byte[]> files;
    private final SequencedSet<String> refused = new LinkedHashSet<>();

    /** @param files the set's files by name, as the VDR names them ({@code background.png}) */
    SetFiles(Map<String, byte[]> files) {
        this.files = files;
    }

    /** The addresses refused so far, in the order iText asked for them. */
    SequencedSet<String> refused() {
        return refused;
    }

    @Override
    public byte[] getByteArrayByUrl(URL url) {
        String address = url.toExternalForm();
        if (address.startsWith(VDR_TEMPLATES)) {
            byte[] file = files.get(address.substring(address.lastIndexOf('/') + 1));
            if (file != null) {
                return file;
            }
        }
        if (!address.equals(EMPTY_ADDRESS)) {
            refused.add(address);
        }
        return null;
    }

    @Override
    public InputStream getInputStreamByUrl(URL url) {
        byte[] file = getByteArrayByUrl(url);
        return file == null ? null : new ByteArrayInputStream(file);
    }

    private static String emptyAddress() {
        try {
            return new UriResolver("").resolveAgainstBaseUri("").toExternalForm();
        } catch (MalformedURLException e) {
            throw new IllegalStateException(e);
        }
    }
}
