/*
 * This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0. If a copy of the MPL was not
 * distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.
 *
 * Copied from mosip/mimoto v0.21.0, src/main/java/io/mosip/mimoto/util/LocaleUtils.java: the methods the HTML print
 * path calls.
 */
package asia.mosip.renderer.mimoto;

import java.util.Locale;

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
}
