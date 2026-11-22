/*
 * This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0. If a copy of the MPL was not
 * distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.
 *
 * Copied from mosip/mimoto v0.21.0, src/main/java/io/mosip/mimoto/util/LocaleUtils.java: the methods the HTML print
 * path calls.
 */
package asia.mosip.renderer.mimoto;

import asia.mosip.renderer.mimoto.Wellknown.CredentialDisplayResponseDto;
import asia.mosip.renderer.mimoto.Wellknown.CredentialIssuerDisplayResponse;

import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;

public class LocaleUtils {
    // Method to convert the input locale strings into 3-letter codes and compare
    public static boolean matchesLocale(String localeString1, String localeString2) {
        if(localeString1 == null || localeString2 == null){
            return false;
        }

        String locale1Iso3Language = Locale.forLanguageTag(localeString1).getISO3Language(); // 3-letter code for locale1
        String locale2Iso3Language = Locale.forLanguageTag(localeString2).getISO3Language(); // 3-letter code for locale2

        return locale1Iso3Language.equals(locale2Iso3Language);
    }

    public static String resolveLocaleWithFallback(Map<String, CredentialDisplayResponseDto> credentialSubject, String locale) {
        String selectedLocale = null;

        // Iterate through the credentials to find a display object that supports the requested locale. If none is found, use the first available display object.
        for (String VCProperty : credentialSubject.keySet()) {
            List<CredentialIssuerDisplayResponse> displayList = credentialSubject.get(VCProperty).getDisplay();
            // If no matching locale is found for any of the fields, use the locale of the first display object
            if(selectedLocale == null && displayList!=null && !displayList.isEmpty()){
                selectedLocale = displayList.get(0).getLocale();
            }
            // Check if any display object supports the requested locale
            Optional<CredentialIssuerDisplayResponse> filteredResponse = displayList.stream()
                    .filter(obj -> matchesLocale(obj.getLocale(), locale))
                    .findFirst();
            if (filteredResponse.isPresent()) {
                selectedLocale = filteredResponse.get().getLocale();
                break; // Break once a matching record is found
            }
        }

        return selectedLocale;
    }
}
