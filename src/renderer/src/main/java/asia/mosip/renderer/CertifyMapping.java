package asia.mosip.renderer;

import com.fasterxml.jackson.databind.JsonNode;
import java.io.StringWriter;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.apache.velocity.VelocityContext;
import org.apache.velocity.app.VelocityEngine;
import org.apache.velocity.exception.VelocityException;
import org.apache.velocity.tools.generic.DateTool;
import org.apache.velocity.tools.generic.EscapeTool;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * The claims Certify 0.14 signs for a record, computed by Certify's steps on Certify's library versions (Velocity 1.7,
 * org.json 20241224). The steps are read from the bytecode of ghcr.io/mosip-asia/ait-certify's certify-service.jar:
 * {@code CertifyIssuanceServiceImpl.getVerifiableCredential} (ldp_vc) and
 * {@code VelocityTemplatingEngineImpl.format}. The record goes first through this platform's Data-provider plugin's
 * step ({@link TemplateRecord}, the renderer's copy of it). README.md, "How it maps the claims", lists the variables.
 */
final class CertifyMapping {

    /** Certify would not sign this record with this vc_template; the message says why. */
    static final class Refused extends Exception {
        Refused(String message) {
            super(message);
        }
    }

    static final String V2 = "https://www.w3.org/ns/credentials/v2";

    // Fixed stand-ins for what Certify knows only at issuance: visibly placeholders.
    static final String TOKEN_SUB = "preview-sub";
    static final String TOKEN_CLIENT_ID = "preview-client";
    static final String HOLDER_ID = "did:example:holder";
    static final String DID_URL = "did:example:issuer";
    static final String TEMPLATE_NAME = "preview-template-name";
    static final String VALID_FROM = "2000-01-01T00:00:00.000Z";
    static final String VALID_UNTIL = "2001-12-31T00:00:00.000Z";  // + P730D, Certify's default expiry
    static final String STATUS_LIST = "https://status-list.example/preview";

    private CertifyMapping() {}

    /**
     * The credentialSubject Certify signs: the plugin's record step on {@code answer} (the Adapter's answer as
     * text), Certify's template variables, Velocity 1.7 on {@code vcTemplate} (the text template-sync stores), then
     * org.json on the result.
     *
     * @throws Refused when the plugin refuses the answer, Velocity can't evaluate the text, or org.json can't read
     *     the result
     */
    static JSONObject credentialSubject(String answer, String vcTemplate, JsonNode credentialFile) throws Refused {
        JSONObject data;
        try {
            data = TemplateRecord.shape(TemplateRecord.record(answer), TemplateRecord.STRUCTURED_KEYS);
        } catch (JSONException e) {
            throw new Refused("Certify refuses this record (adapter_error): the Adapter's answer is not the expected"
                    + " JSON: " + e.getMessage());
        } catch (IllegalArgumentException e) {
            throw new Refused("Certify refuses this record (adapter_error): " + e.getMessage());
        }
        // IssuerDataProviderPlugin.fetchData
        data.put("tokenSub", TOKEN_SUB);
        data.put("tokenClientId", TOKEN_CLIENT_ID);
        // CertifyIssuanceServiceImpl.getVerifiableCredential, ldp_vc: on the record, then into the template's map
        data.put("type", strings(credentialFile.path("credential_type").asText("")));
        List<String> purposes = list(credentialFile.path("credential_status_purpose"));
        if (!purposes.isEmpty() && list(credentialFile.path("context")).contains(V2)) {
            Map<String, Object> status = new HashMap<>();  // StatusListCredentialService.addCredentialStatus
            status.put("id", STATUS_LIST + "#0");
            status.put("type", "BitstringStatusListEntry");
            status.put("statusPurpose", purposes.get(0));
            status.put("statusListIndex", "0");
            status.put("statusListCredential", STATUS_LIST);
            data.put("credentialStatus", status);
        }
        Map<String, Object> params = new HashMap<>();
        params.put("templateName", TEMPLATE_NAME);
        params.put("didUrl", DID_URL);
        data.put("_holderId", HOLDER_ID);
        params.putAll(data.toMap());
        params.put("validFrom", VALID_FROM);
        params.put("validUntil", VALID_UNTIL);
        // VelocityTemplatingEngineImpl.format
        params.put("_dateTool", new DateTool());
        params.put("_esc", new EscapeTool());
        params.put("_issuer", DID_URL);
        VelocityEngine engine = new VelocityEngine();  // VelocityTemplatingEngineImpl.initialize
        engine.setProperty("input.encoding", "UTF-8");
        engine.setProperty("output.encoding", "UTF-8");
        engine.init();
        StringWriter out = new StringWriter();
        try {
            engine.evaluate(new VelocityContext(params), out, TEMPLATE_NAME, vcTemplate);
        } catch (VelocityException e) {
            throw new Refused("Certify can't evaluate the credential file's vc_template: " + e.getMessage());
        }
        JSONObject credential;
        try {
            credential = new JSONObject(out.toString());
        } catch (JSONException e) {
            throw new Refused("Certify can't read what the vc_template makes as JSON (json_processing_error): "
                    + e.getMessage());
        }
        JSONObject subject = credential.optJSONObject("credentialSubject");
        if (subject == null) {
            throw new Refused("the vc_template makes no credentialSubject object");
        }
        return subject;
    }

    private static List<String> strings(String commaSeparated) {
        return commaSeparated.isEmpty() ? List.of() : Arrays.asList(commaSeparated.split(","));
    }

    private static List<String> list(JsonNode array) {
        List<String> out = new ArrayList<>();
        array.forEach(n -> out.add(n.asText()));
        return out;
    }
}
