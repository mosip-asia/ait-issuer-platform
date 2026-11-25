package asia.mosip.renderer;

import asia.mosip.renderer.mimoto.CredentialPDFGeneratorService;
import asia.mosip.renderer.mimoto.Wellknown.CredentialDefinitionResponseDto;
import asia.mosip.renderer.mimoto.Wellknown.CredentialDisplayResponseDto;
import asia.mosip.renderer.mimoto.Wellknown.CredentialSupportedDisplayResponse;
import asia.mosip.renderer.mimoto.Wellknown.CredentialsSupportedResponse;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.Semaphore;

/**
 * The renderer: one call, POST /render, that maps a record to claims the way Certify 0.14 does and prints them the
 * way ait-mimoto's HTML path does (README.md). JSON in, the PDF or the HTML it is printed from out. Nothing is written to disk. Nothing is kept
 * between calls, unless a template uses reflection to reach past Velocity (README.md, "Limits").
 */
public final class RendererServer {

    // Bytes. VC Lab takes at most 20 MB of files; the Background goes in as base64 (a third more) and the credential
    // file twice. A Background alone at the limit is 27 MB and fits; a set of several near-limit files can pass it
    // (413, which VC Lab shows as a 502).
    static final int MAX_REQUEST = 32 * 1024 * 1024;

    // Spring Boot's ObjectMapper ignores unknown properties, so Mimoto does too.
    private static final ObjectMapper JSON = new ObjectMapper()
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);

    private static final CredentialPDFGeneratorService PRINTER = new CredentialPDFGeneratorService();

    // At most four requests are read, printed and answered at once; the others wait their turn, first come first
    // served. A request holds its body, a Background and a PDF, so this bounds the heap that previews take.
    static final int RENDERS_AT_ONCE = 4;
    private static final Semaphore RENDERS = new Semaphore(RENDERS_AT_ONCE, true);

    static final int CHUNK = 64 * 1024;  // bytes per write: see send()

    /**
     * POST /render's body. record is the Adapter's answer as text, read as the plugin reads it; vcTemplate is the credential file's vc_template as the
     * text template-sync stores for Certify; credentialFile is Certify's credential file, as VC Lab holds it;
     * backgroundImage is the Background as a PNG data URI, "" for none, or null for the credential file's own address; output is "pdf" (the default) or "html", the
     * evaluated template that the PDF would be printed from.
     */
    record RenderRequest(String template, String record, String vcTemplate, JsonNode credentialFile,
                         String backgroundImage, String locale, String output) {}

    public static void main(String[] args) throws IOException {
        int port = Integer.parseInt(System.getenv().getOrDefault("PORT", "8080"));
        HttpServer server = HttpServer.create(new InetSocketAddress(port), 0);
        server.createContext("/health", exchange -> {
            exchange.getRequestBody().close();
            send(exchange, 200, "application/json", "{\"status\":\"UP\",\"service\":\"renderer\"}".getBytes(StandardCharsets.UTF_8));
        });
        server.createContext("/render", RendererServer::render);
        server.setExecutor(Executors.newVirtualThreadPerTaskExecutor());
        server.start();
        System.err.println("renderer listening on :" + port);
    }

    private static void render(HttpExchange exchange) throws IOException {
        try (exchange) {
            if (!"POST".equals(exchange.getRequestMethod())) {
                error(exchange, 405, "use POST");
                return;
            }
            RENDERS.acquireUninterruptibly();
            try {
                print(exchange);
            } catch (OutOfMemoryError e) {
                error(exchange, 503, "the renderer ran out of memory for this print; try again, or use a smaller Background");
            } finally {
                RENDERS.release();
            }
        }
    }

    private static void print(HttpExchange exchange) throws IOException {
        byte[] body = exchange.getRequestBody().readNBytes(MAX_REQUEST + 1);
        if (body.length > MAX_REQUEST) {
            error(exchange, 413, "request is larger than " + MAX_REQUEST / (1024 * 1024) + " MB");
            return;
        }
        RenderRequest request;
        try {
            request = JSON.readValue(body, RenderRequest.class);
        } catch (IOException e) {
            error(exchange, 400, "expected the JSON render request: " + e.getMessage());
            return;
        }
        if (request.template() == null || request.record() == null
                || request.vcTemplate() == null || request.credentialFile() == null) {
            error(exchange, 400, "template, record (the Adapter's answer as text), vcTemplate and credentialFile are required");
            return;
        }
        boolean html = "html".equals(request.output());
        CredentialsSupportedResponse metadata;
        try {
            metadata = issuerMetadata(request.credentialFile());
        } catch (IllegalArgumentException e) {
            error(exchange, 400, "credentialFile isn't shaped as Certify's credential file: " + e.getMessage());
            return;
        }
        Map<String, Object> credentialSubject;
        try {
            // As the Wallet gets it: the signed credential's JSON text, read by Jackson.
            credentialSubject = JSON.readValue(CertifyMapping.credentialSubject(request.record(),
                    request.vcTemplate(), request.credentialFile()).toString(), new TypeReference<>() {});
        } catch (CertifyMapping.Refused e) {
            error(exchange, 422, e.getMessage());
            return;
        }
        // The set's files at their VDR address: today the Background, as the PNG its data URI holds.
        String background = request.backgroundImage();
        SetFiles files = new SetFiles(background == null || background.isEmpty() ? Map.of()
                : Map.of("background.png", Base64.getDecoder().decode(background.substring(background.indexOf(',') + 1))));
        String merged;
        byte[] pdf;
        try {
            merged = PRINTER.generateHtml(request.template(), credentialSubject, metadata,
                    background, request.locale() != null ? request.locale() : "en");
            // Printed for the quick view too, which must not show what the print can't load.
            pdf = PRINTER.toPdf(merged, files);
        } catch (Exception e) {
            // The input parsed, so what failed is printing it, as Mimoto would fail: the message is the answer.
            // Velocity's names the template's line and column; iText's names what it couldn't lay out.
            e.printStackTrace();
            error(exchange, 422, String.valueOf(e.getMessage()));
            return;
        } catch (StackOverflowError e) {
            // Velocity parses and renders nested blocks recursively.
            error(exchange, 422, "the template nests its blocks too deep to print");
            return;
        }
        if (!files.refused().isEmpty()) {
            error(exchange, 422, "the template loads " + String.join(", ", files.refused()) + ": the preview loads"
                    + " only data: URIs and the set's files at " + SetFiles.VDR_TEMPLATES + "<any folders>/<file name>"
                    + " (background.png, when a Background is loaded)");
            return;
        }
        send(exchange, 200, html ? "text/html; charset=utf-8" : "application/pdf",
                html ? merged.getBytes(StandardCharsets.UTF_8) : pdf);
    }

    /**
     * What Certify publishes for an ldp_vc credential file, in the shape Mimoto reads: display stays display,
     * display_order becomes order, and credential_subject becomes credential_definition.credentialSubject.
     */
    static CredentialsSupportedResponse issuerMetadata(JsonNode credentialFile) {
        CredentialsSupportedResponse metadata = new CredentialsSupportedResponse();
        metadata.setDisplay(JSON.convertValue(credentialFile.get("display"),
                new TypeReference<List<CredentialSupportedDisplayResponse>>() {}));
        metadata.setOrder(JSON.convertValue(credentialFile.get("display_order"), new TypeReference<List<String>>() {}));
        CredentialDefinitionResponseDto definition = new CredentialDefinitionResponseDto();
        definition.setCredentialSubject(JSON.convertValue(credentialFile.get("credential_subject"),
                new TypeReference<Map<String, CredentialDisplayResponseDto>>() {}));
        metadata.setCredentialDefinition(definition);
        return metadata;
    }

    private static void error(HttpExchange exchange, int status, String message) throws IOException {
        send(exchange, status, "application/json", JSON.writeValueAsBytes(Map.of("error", message)));
    }

    private static void send(HttpExchange exchange, int status, String type, byte[] body) throws IOException {
        exchange.getResponseHeaders().set("Content-Type", type);
        exchange.sendResponseHeaders(status, body.length);
        // In chunks: the JDK keeps a direct buffer as large as the largest single write for each thread that wrote it,
        // so one write of a whole PDF would pin that much memory outside the heap for good.
        try (OutputStream out = exchange.getResponseBody()) {
            for (int off = 0; off < body.length; off += CHUNK) {
                out.write(body, off, Math.min(CHUNK, body.length - off));
            }
        }
    }
}
