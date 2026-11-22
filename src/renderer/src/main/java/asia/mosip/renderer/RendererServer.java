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
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executors;

/**
 * The renderer: one call, POST /render, that prints a credential the way Mimoto 0.21's HTML path does (README.md).
 * JSON in, PDF out. Nothing is written to disk; nothing is kept between calls.
 */
public final class RendererServer {

    static final int MAX_REQUEST = 32 * 1024 * 1024;  // bytes; VC Lab sends at most an 8 MB set, base64 grows it

    // Spring Boot's ObjectMapper ignores unknown properties, so Mimoto does too.
    private static final ObjectMapper JSON = new ObjectMapper()
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);

    private static final CredentialPDFGeneratorService PRINTER = new CredentialPDFGeneratorService();

    /** POST /render's body. credentialFile is Certify's credential file, as VC Lab holds it. */
    record RenderRequest(String template, Map<String, Object> credentialSubject, JsonNode credentialFile,
                         String backgroundImage, String locale) {}

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
            if (request.template() == null || request.credentialSubject() == null || request.credentialFile() == null) {
                error(exchange, 400, "template, credentialSubject and credentialFile are required");
                return;
            }
            CredentialsSupportedResponse metadata;
            try {
                metadata = issuerMetadata(request.credentialFile());
            } catch (IllegalArgumentException e) {
                error(exchange, 400, "credentialFile isn't shaped as Certify's credential file: " + e.getMessage());
                return;
            }
            byte[] pdf;
            try {
                pdf = PRINTER.generatePdf(request.template(), request.credentialSubject(), metadata,
                        request.backgroundImage(), request.locale() != null ? request.locale() : "en");
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
            } catch (OutOfMemoryError e) {
                error(exchange, 503, "the renderer ran out of memory for this print; try again, or use a smaller Background");
                return;
            }
            send(exchange, 200, "application/pdf", pdf);
        }
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
        try (OutputStream out = exchange.getResponseBody()) {
            out.write(body);
        }
    }
}
