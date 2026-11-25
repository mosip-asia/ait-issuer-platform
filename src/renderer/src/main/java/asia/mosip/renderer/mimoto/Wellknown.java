/*
 * This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0. If a copy of the MPL was not
 * distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.
 *
 * Copied from mosip/mimoto v0.21.0, src/main/java/io/mosip/mimoto/dto/mimoto/: CredentialsSupportedResponse,
 * CredentialDefinitionResponseDto, CredentialSupportedDisplayResponse, CredentialIssuerDisplayResponse and
 * CredentialDisplayResponseDto, plus dto/BackgroundImageDTO and dto/LogoDTO. Kept: the fields Mimoto's
 * HTML print path reads and their JSON names. Left out: validation, Swagger and Gson annotations, and the fields the
 * print path never reads.
 */
package asia.mosip.renderer.mimoto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;
import java.util.Map;

/** One entry of an issuer's credential_configurations_supported, as Mimoto reads it. */
public final class Wellknown {
    private Wellknown() {}

    @Data
    public static class CredentialsSupportedResponse {
        @JsonProperty("credential_definition")
        private CredentialDefinitionResponseDto credentialDefinition;

        @JsonProperty("display")
        private List<CredentialSupportedDisplayResponse> display;

        private List<String> order;
    }

    @Data
    public static class CredentialDefinitionResponseDto {
        @JsonProperty("credentialSubject")
        private Map<String, CredentialDisplayResponseDto> credentialSubject;
    }

    @Data
    public static class CredentialSupportedDisplayResponse {
        String name;
        String locale;
        LogoDTO logo;
        @JsonProperty("background_image")
        BackgroundImageDTO backgroundImage;
        @JsonProperty("background_color")
        String backgroundColor;
        @JsonProperty("text_color")
        String textColor;
    }

    @Data
    public static class CredentialIssuerDisplayResponse {
        @JsonProperty("name")
        private String name;
        @JsonProperty("locale")
        private String locale;
    }

    @Data
    public static class CredentialDisplayResponseDto {
        @JsonProperty("display")
        private List<CredentialIssuerDisplayResponse> display;
    }

    @Data
    public static class BackgroundImageDTO {
        String uri;
    }

    @Data
    public static class LogoDTO {
        String url;
        String alt_text;
    }
}
