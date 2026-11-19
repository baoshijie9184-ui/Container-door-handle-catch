package com.ruanzhu.doorhandle.module.ai.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class PersonalModelQuotaJsonTest {
    private final ObjectMapper json = new ObjectMapper()
            .setSerializationInclusion(JsonInclude.Include.NON_NULL)
            .enable(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES);

    @Test void lastPageAndUnlimitedModelHaveExplicitNulls() throws Exception {
        var page = json.readTree(json.writeValueAsBytes(new PersonalModelQuotaService.Page(List.of(), null)));
        assertTrue(page.required("nextCursor").isNull());
        var model = new PersonalModelQuotaService.MineModel("id", "provider", "model", true, true,
                null, 0, 0, null, null, 1L, null);
        var row = json.readTree(json.writeValueAsBytes(model));
        for (String key : List.of("totalTokens", "availableTokens", "expiresAt", "enterpriseBlockedReason"))
            assertTrue(row.required(key).isNull(), key);
    }

    @Test void terminalReceiptsRoundTripWithNullableBalancesAndReasons() throws Exception {
        for (String action : List.of("APPROVE", "REJECT", "CANCEL")) {
            String reason = action.equals("CANCEL") ? null : "review";
            Long after = action.equals("APPROVE") ? 1L : null;
            var decision = new PersonalModelQuotaWorkflow.DecisionV1(action, 1, "request", "digest", reason, 0, null, after);
            assertEquals(decision, json.readValue(json.writeValueAsBytes(decision), decision.getClass()));
            var audit = new PersonalModelQuotaWorkflow.AuditV1("model", 1, reason);
            assertEquals(audit, json.readValue(json.writeValueAsBytes(audit), audit.getClass()));
        }
    }
}
