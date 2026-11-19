package com.ruanzhu.doorhandle.module.detection.controller;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class OssPreviewFailureTest {
    @Test void explicitOverduePaymentIsReported() {
        assertThat(OssPreviewController.classify("AccessDenied", "Your account is in arrears.")).isEqualTo("BILLING_OVERDUE");
        assertThat(OssPreviewController.classify("InsufficientBalance", "")).isEqualTo("BILLING_OVERDUE");
    }

    @Test void ambiguousDenialsAndMissingObjectsKeepTheirOwnCause() {
        assertThat(OssPreviewController.classify("UserDisable", "UserDisable")).isEqualTo("DISABLED");
        assertThat(OssPreviewController.classify("BucketDisable", "Bucket is disabled")).isEqualTo("DISABLED");
        assertThat(OssPreviewController.classify("AccessDenied", "Access denied by policy")).isEqualTo("ACCESS_DENIED");
        assertThat(OssPreviewController.classify("NoSuchKey", "The specified key does not exist.")).isEqualTo("MISSING");
        assertThat(OssPreviewController.classify("InvalidAccessKeyId", "")).isEqualTo("CONFIGURATION");
    }
}
