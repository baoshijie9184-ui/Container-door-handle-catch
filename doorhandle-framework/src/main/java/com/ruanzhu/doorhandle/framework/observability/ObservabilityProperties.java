package com.ruanzhu.doorhandle.framework.observability;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** 技术遥测独立于业务审计、额度结算；默认不向外发送。 */
@ConfigurationProperties("doorhandle.observability")
public class ObservabilityProperties {
    private boolean tracingEnabled;
    private String endpoint = "";
    private String publicKeyFile = "";
    private String secretKeyFile = "";
    private String metricsTokenFile = "";
    private String serviceName = "doorhandle-monolith";
    private double sampleRatio = 0.1;
    private int queueSize = 1024;
    private int batchSize = 128;
    private int timeoutMillis = 3000;
    public boolean isTracingEnabled(){return tracingEnabled;}
    public void setTracingEnabled(boolean value){tracingEnabled=value;}
    public String getEndpoint(){return endpoint;}
    public void setEndpoint(String value){endpoint=value;}
    public String getPublicKeyFile(){return publicKeyFile;}
    public void setPublicKeyFile(String value){publicKeyFile=value;}
    public String getSecretKeyFile(){return secretKeyFile;}
    public void setSecretKeyFile(String value){secretKeyFile=value;}
    public String getMetricsTokenFile(){return metricsTokenFile;}
    public void setMetricsTokenFile(String value){metricsTokenFile=value;}
    public String getServiceName(){return serviceName;}
    public void setServiceName(String value){serviceName=value;}
    public double getSampleRatio(){return sampleRatio;}
    public void setSampleRatio(double value){sampleRatio=value;}
    public int getQueueSize(){return queueSize;}
    public void setQueueSize(int value){queueSize=value;}
    public int getBatchSize(){return batchSize;}
    public void setBatchSize(int value){batchSize=value;}
    public int getTimeoutMillis(){return timeoutMillis;}
    public void setTimeoutMillis(int value){timeoutMillis=value;}
}
