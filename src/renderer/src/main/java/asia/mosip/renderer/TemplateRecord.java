package asia.mosip.renderer;

import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * The record as Certify's template takes it: the renderer's copy of the Data-provider plugin's one change to the
 * Adapter's values ({@code IssuerDataProviderPlugin.shape} and {@code escapeForQuotedTemplate} in
 * {@code src/issuer/}). Nothing makes the two match (ADR 0002): change both together.
 */
final class TemplateRecord {

    /** The plugin's default {@code mosip.certify.adapter.structured-keys}: the one claim served as an array. */
    static final Set<String> STRUCTURED_KEYS = Set.of("courses");

    private TemplateRecord() {}

    /**
     * The record for Certify's template, which substitutes every claim into a quoted slot ({@code "${fullName}"})
     * except structured fields in {@code structuredKeys} (such as {@code ${courses}}): every top-level string escaped,
     * structured keys as JSON text, any other primitive value as it is.
     *
     * @throws IllegalArgumentException naming the key, for a {@code null}, an unconfigured structured value or a
     *     structured key that is not an array (the plugin's {@code adapter_error})
     */
    static JSONObject shape(JSONObject record, Set<String> structuredKeys) {
        JSONObject data = new JSONObject();
        for (String key : record.keySet()) {
            Object value = record.get(key);
            if (value == JSONObject.NULL) {
                throw new IllegalArgumentException("has null for " + key);
            }
            boolean structured = value instanceof JSONObject || value instanceof JSONArray;
            if (structuredKeys.contains(key) ? !(value instanceof JSONArray) : structured) {
                throw new IllegalArgumentException("has a " + value.getClass().getSimpleName() + " for " + key);
            }
            if (value instanceof String text) {
                data.put(key, escapeForQuotedTemplate(text));
            } else if (structured) {
                data.put(key, value.toString());
            } else {
                data.put(key, value);
            }
        }
        return data;
    }

    /**
     * JSON string escaping without the surrounding quotes, ASCII only, as Python's {@code json.dumps(value)[1:-1]}
     * writes it: a quote or a backslash gets a backslash before it, newline, carriage return, tab, backspace and form
     * feed get their short escapes, and every other character outside printable ASCII becomes a backslash, a
     * {@code u} and its four hex digits (per UTF-16 code unit, so a surrogate pair is two escapes).
     */
    static String escapeForQuotedTemplate(String value) {
        StringBuilder out = new StringBuilder(value.length());
        for (char c : value.toCharArray()) {
            switch (c) {
                case '"' -> out.append("\\\"");
                case '\\' -> out.append("\\\\");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                case '\b' -> out.append("\\b");
                case '\f' -> out.append("\\f");
                default -> {
                    if (c < 0x20 || c > 0x7e) {
                        out.append(String.format("\\u%04x", (int) c));
                    } else {
                        out.append(c);
                    }
                }
            }
        }
        return out.toString();
    }
}
