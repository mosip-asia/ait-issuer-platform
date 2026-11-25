/*
 * This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0. If a copy of the MPL was not
 * distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.
 *
 * Copied from mosip/mimoto v0.21.0, src/main/java/io/mosip/mimoto/service/impl/LdpVcCredentialFormatHandler.java:
 * loadDisplayPropertiesFromWellknown and its two fallbacks, and IssuerConfigUtil.camelToTitleCase. Changed: no Spring
 * and no logging. Left out: building the credential request and reading the claims out of a signed credential (the
 * renderer is handed the claims).
 */
package asia.mosip.renderer.mimoto;

import asia.mosip.renderer.mimoto.Wellknown.CredentialDisplayResponseDto;
import asia.mosip.renderer.mimoto.Wellknown.CredentialIssuerDisplayResponse;
import asia.mosip.renderer.mimoto.Wellknown.CredentialsSupportedResponse;

import java.util.*;

public class LdpVcCredentialFormatHandler {

    private void addFallbackDisplayProperties(
            Map<String, Object> credentialProperties,
            LinkedHashMap<String, CredentialIssuerDisplayResponse> localizedDisplayMap,
            String resolvedLocale) {
        // fallback for missing display properties from issuer well-known
        Set<String> credentialFields = credentialProperties.keySet();
        Set<String> missingDisplayFields = new HashSet<>(credentialFields);
        missingDisplayFields.removeAll(localizedDisplayMap.keySet());
        // remove metadata fields that are not part of the display properties
        missingDisplayFields.remove("id");

        // Generate fallbacks for fields without well-known display properties
        for (String missingField : missingDisplayFields) {
            String displayName = camelToTitleCase(missingField);

            CredentialIssuerDisplayResponse fallbackDisplay = new CredentialIssuerDisplayResponse();
            fallbackDisplay.setName(displayName);
            fallbackDisplay.setLocale("en");

            localizedDisplayMap.put(missingField, fallbackDisplay);
        }
    }

    public LinkedHashMap<String, Map<CredentialIssuerDisplayResponse, Object>> loadDisplayPropertiesFromWellknown(
            Map<String, Object> credentialProperties,
            CredentialsSupportedResponse credentialsSupportedResponse,
            String userLocale) {

        LinkedHashMap<String, Map<CredentialIssuerDisplayResponse, Object>> displayProperties = new LinkedHashMap<>();
        Set<String> orderedKeys = Optional.ofNullable(credentialsSupportedResponse.getOrder())
                .map(LinkedHashSet::new) // preserve order
                .orElse(new LinkedHashSet<>());

        // Add remaining keys from credentialProperties that are not already in orderedKeys
        for (String key : credentialProperties.keySet()) {
            orderedKeys.add(key);
        }

        // LDP VC format — display config is in "credential_definition.credential_subject"
        if (credentialsSupportedResponse.getCredentialDefinition() == null ||
                credentialsSupportedResponse.getCredentialDefinition().getCredentialSubject() == null) {
            return buildFallbackDisplayProperties(credentialProperties, new ArrayList<>(orderedKeys));
        }

        Map<String, CredentialDisplayResponseDto> displayConfigMap =
                credentialsSupportedResponse.getCredentialDefinition().getCredentialSubject();

        String resolvedLocale = LocaleUtils.resolveLocaleWithFallback(displayConfigMap, userLocale);

        LinkedHashMap<String, CredentialIssuerDisplayResponse> localizedDisplayMap = new LinkedHashMap<>();

        if (resolvedLocale != null) {
            displayConfigMap.forEach((key, dto) -> {
                dto.getDisplay().stream()
                        .filter(display -> LocaleUtils.matchesLocale(display.getLocale(), resolvedLocale))
                        .findFirst()
                        .ifPresent(display -> localizedDisplayMap.put(key, display));
            });
        }

        addFallbackDisplayProperties(credentialProperties, localizedDisplayMap, resolvedLocale);

        List<String> fieldKeys = (orderedKeys != null && !orderedKeys.isEmpty())
                ? new ArrayList<>(orderedKeys)
                : new ArrayList<>(localizedDisplayMap.keySet());

        for (String key : fieldKeys) {
            CredentialIssuerDisplayResponse display = localizedDisplayMap.get(key);
            Object value = credentialProperties.get(key);
            if (display != null && value != null) {
                displayProperties.put(key, Map.of(display, value));
            }
        }

        return displayProperties;
    }

    private LinkedHashMap<String, Map<CredentialIssuerDisplayResponse, Object>> buildFallbackDisplayProperties(
            Map<String, Object> credentialProperties,
            List<String> orderedKeys) {

        LinkedHashMap<String, Map<CredentialIssuerDisplayResponse, Object>> displayProperties = new LinkedHashMap<>();

        // Determine field order (prefer issuer-provided 'order' if any)
        List<String> fieldKeys = (orderedKeys != null && !orderedKeys.isEmpty())
                ? new ArrayList<>(orderedKeys)
                : new ArrayList<>(credentialProperties.keySet());

        // Exclude non-claim metadata
        fieldKeys.remove("id");

        // Build default display entries from claims
        for (String key : fieldKeys) {
            Object value = credentialProperties.get(key);
            if (value == null) {
                continue;
            }

            // Generate fallback display using vc keys
            CredentialIssuerDisplayResponse display = new CredentialIssuerDisplayResponse();
            display.setName(camelToTitleCase(key));
            display.setLocale("en");

            displayProperties.put(key, Map.of(display, value));
        }
        return displayProperties;
    }

    // IssuerConfigUtil.camelToTitleCase
    public static String camelToTitleCase(String input) {
        if (input == null || input.isEmpty()) return input;

        // Insert space before:
        // 1. Lowercase followed by uppercase (e.g., pinFor -> pin For)
        // 2. Acronym followed by normal word (e.g., PRACondition -> PRA Condition)
        String result = input.replaceAll("(?<=[a-z])(?=[A-Z])|(?<=[A-Z]{2,})(?=[A-Z][a-z])", " ");

        // Capitalize first letter of each word, preserve acronyms
        String[] words = result.split(" ");
        StringBuilder finalResult = new StringBuilder();

        for (String word : words) {
            if (word.matches("[A-Z]{2,}")) {
                // Acronym (all uppercase, length >= 2)
                finalResult.append(word);
            } else {
                // Capitalize normally
                finalResult.append(Character.toUpperCase(word.charAt(0)))
                        .append(word.substring(1));
            }
            finalResult.append(" ");
        }

        return finalResult.toString().trim();
    }
}
