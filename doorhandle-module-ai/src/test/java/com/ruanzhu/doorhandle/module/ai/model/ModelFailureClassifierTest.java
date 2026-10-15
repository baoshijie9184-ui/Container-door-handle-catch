package com.ruanzhu.doorhandle.module.ai.model;

import io.agentscope.core.model.transport.HttpTransportException;
import io.agentscope.extensions.model.openaiofficial.OpenAIOfficialModelException;
import org.junit.jupiter.api.Test;
import java.io.IOException;
import java.util.concurrent.TimeoutException;
import static com.ruanzhu.doorhandle.module.ai.model.ModelFailureClassifier.Failure.*;
import static org.assertj.core.api.Assertions.*;

class ModelFailureClassifierTest {
    @Test void recognizesQuotaBodiesUnderDifferentStatusesAndWrappedExceptions() {
        for (String body : new String[]{"insufficient_quota", "insufficient_balance", "Arrearage", "余额不足", "billing_hard_limit_reached"})
            for (int status : new int[]{400, 402, 403, 429})
                assertThat(ModelFailureClassifier.classify(new IllegalStateException("wrapper", new HttpTransportException("upstream", status, body)))).isEqualTo(QUOTA);
        assertThat(ModelFailureClassifier.classify(new HttpTransportException("upstream", 402, ""))).isEqualTo(QUOTA);
        assertThat(ModelFailureClassifier.classify(new OpenAIOfficialModelException("Response failed: insufficient_quota", "model"))).isEqualTo(QUOTA);
    }
    @Test void separatesTransientAuthenticationAndRequestErrors() {
        for (int status : new int[]{408, 409, 429, 500, 503})
            assertThat(ModelFailureClassifier.classify(new HttpTransportException("upstream", status, ""))).isEqualTo(TRANSIENT);
        for (int status : new int[]{401, 403})
            assertThat(ModelFailureClassifier.classify(new HttpTransportException("upstream", status, "invalid key"))).isEqualTo(AUTH);
        assertThat(ModelFailureClassifier.classify(new HttpTransportException("bad schema", 400, ""))).isEqualTo(OTHER);
        assertThat(ModelFailureClassifier.classify(new IllegalArgumentException("insufficient_quota"))).isEqualTo(OTHER);
    }
    @Test void recognizesWrappedNetworkErrorsEvenWhenAdapterHasNoHttpStatus() {
        assertThat(ModelFailureClassifier.classify(new OpenAIOfficialModelException("safe", new IOException("network"), "model"))).isEqualTo(TRANSIENT);
        assertThat(ModelFailureClassifier.classify(new IllegalStateException("retry exhausted", new TimeoutException()))).isEqualTo(TRANSIENT);
    }
}
