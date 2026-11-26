package asia.mosip.renderer;

import com.itextpdf.styledxmlparser.resolver.resource.IResourceRetriever;
import com.itextpdf.styledxmlparser.resolver.resource.UriResolver;
import java.io.InputStream;
import java.net.MalformedURLException;
import java.net.URL;
import java.util.LinkedHashSet;
import java.util.SequencedSet;

/**
 * All iText may load while it prints: nothing but data: URIs, which iText decodes itself (the Background is one, as
 * {@code $backgroundImage}). It asks this for every other address (an image, a font, a stylesheet, an SVG's own
 * references), and each is refused and noted in {@link #refused()}: iText logs a resource it can't load and prints
 * without it, so the caller fails the print instead, as the Wallet would print what the preview left out.
 */
final class RefusedAddresses implements IResourceRetriever {

    // Where iText resolves an empty address, src="": its base, the working directory, as no base URI is set (as in
    // Mimoto). The Wallet loads nothing there either, so the demo template's <img src="$logoUrl">, with $logoUrl
    // empty, draws no image and is not refused.
    private static final String EMPTY_ADDRESS = emptyAddress();

    private final SequencedSet<String> refused = new LinkedHashSet<>();

    /** The addresses refused so far, in the order iText asked for them. */
    SequencedSet<String> refused() {
        return refused;
    }

    @Override
    public byte[] getByteArrayByUrl(URL url) {
        String address = url.toExternalForm();
        if (!address.equals(EMPTY_ADDRESS)) {
            refused.add(address);
        }
        return null;
    }

    @Override
    public InputStream getInputStreamByUrl(URL url) {
        getByteArrayByUrl(url);
        return null;
    }

    private static String emptyAddress() {
        try {
            return new UriResolver("").resolveAgainstBaseUri("").toExternalForm();
        } catch (MalformedURLException e) {
            throw new IllegalStateException(e);
        }
    }
}
