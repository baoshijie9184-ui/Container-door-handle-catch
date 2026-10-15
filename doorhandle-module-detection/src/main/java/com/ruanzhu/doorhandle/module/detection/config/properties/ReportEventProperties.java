package com.ruanzhu.doorhandle.module.detection.config.properties;

import jakarta.validation.constraints.*;
import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;
import org.springframework.validation.annotation.Validated;

@Data
@Validated
@Configuration
@ConfigurationProperties(prefix="app.report-events")
public class ReportEventProperties {
    private boolean enabled=false;
    @Pattern(regexp="[A-Za-z0-9][A-Za-z0-9._-]{0,199}") private String topic="detection.report.lifecycle.v1";
    @NotBlank private String consumerGroup="doorhandlecatch-report-receipts-v1";
    @Min(1) @Max(100) private int batchSize=20;
    @Min(500) @Max(60000) private long pollDelayMs=2000;
    @Min(0) @Max(60000) private long initialDelayMs=5000;
    @Min(1000) @Max(30000) private long sendTimeoutMs=10000;
    @Min(5000) @Max(600000) private long leaseMs=60000;
    @Min(1000) @Max(60000) private long retryBaseMs=2000;
    @Min(1000) @Max(3600000) private long retryMaxMs=300000;
    @AssertTrue(message="报告投递租约必须大于两倍发送超时，重试上限不得小于初始间隔")
    public boolean isTimingValid(){return leaseMs>2*sendTimeoutMs&&retryMaxMs>=retryBaseMs;}
}
