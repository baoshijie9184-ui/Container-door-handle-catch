package com.ruanzhu.doorhandle.module.ai.mcp;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix="agentscope.mcp")
public class LocalMcpProperties {
    private boolean enabled;
    private boolean sharedImageCleanupEnabled;
    public boolean isSharedImageCleanupEnabled(){return sharedImageCleanupEnabled;}
    public void setSharedImageCleanupEnabled(boolean value){sharedImageCleanupEnabled=value;}
    private boolean writesEnabled=true;
    public boolean isWritesEnabled(){return writesEnabled;}
    public void setWritesEnabled(boolean value){writesEnabled=value;}
    private boolean durableInstallEnabled;
    private boolean executionReceiptsEnabled;
    private boolean nativeProcessEnabled;
    private boolean nativeInstallEnabled;
    private String nativeInstallHelper="${user.dir}/script/shell/native-fetch-install.py";
    public boolean isNativeInstallEnabled(){return nativeInstallEnabled;}
    public void setNativeInstallEnabled(boolean value){nativeInstallEnabled=value;}
    public String getNativeInstallHelper(){return nativeInstallHelper;}
    public void setNativeInstallHelper(String value){nativeInstallHelper=value;}
    private String nativeProcessHelper="${user.dir}/script/shell/native-fetch-process.py";
    public boolean isNativeProcessEnabled(){return nativeProcessEnabled;}
    public void setNativeProcessEnabled(boolean value){nativeProcessEnabled=value;}
    public String getNativeProcessHelper(){return nativeProcessHelper;}
    public void setNativeProcessHelper(String value){nativeProcessHelper=value;}
    private boolean lifecycleEnabled;
    private boolean installReconciliationEnabled;
    private String installProcessNodeId="";
    public boolean isInstallReconciliationEnabled(){return installReconciliationEnabled;}
    public void setInstallReconciliationEnabled(boolean value){installReconciliationEnabled=value;}
    public String getInstallProcessNodeId(){return installProcessNodeId;}
    public void setInstallProcessNodeId(String value){installProcessNodeId=value;}
    private long storageQuotaBytes=268435456L;
    public long getStorageQuotaBytes(){return storageQuotaBytes;}
    public void setStorageQuotaBytes(long value){storageQuotaBytes=value;}
    private java.util.List<String> approvedGatewayImages=new java.util.ArrayList<>();
    public boolean isLifecycleEnabled(){return lifecycleEnabled;}
    public void setLifecycleEnabled(boolean value){lifecycleEnabled=value;}
    public java.util.List<String> getApprovedGatewayImages(){return approvedGatewayImages;}
    public void setApprovedGatewayImages(java.util.List<String> value){approvedGatewayImages=value==null?new java.util.ArrayList<>():new java.util.ArrayList<>(value);}
    public boolean isExecutionReceiptsEnabled(){return executionReceiptsEnabled;}
    public void setExecutionReceiptsEnabled(boolean value){executionReceiptsEnabled=value;}
    public boolean isDurableInstallEnabled(){return durableInstallEnabled;}
    public void setDurableInstallEnabled(boolean value){durableInstallEnabled=value;}
    private String python="python";
    private String installer="${user.dir}/script/shell/install-local-fetch-mcp.py";
    private String transport="STDIO";
    private String gatewayUrl="http://higress:8080/mcp/fetch";
    private String gatewaySecret="";
    private String gatewayKey="";
    private String gatewayImage="";
    public String getTransport(){return transport;}
    public void setTransport(String value){transport=value;}
    public boolean isGateway(){return "GATEWAY".equals(transport);}
    public String getGatewayUrl(){return gatewayUrl;}
    public void setGatewayUrl(String value){gatewayUrl=value;}
    public String getGatewaySecret(){return gatewaySecret;}
    public void setGatewaySecret(String value){gatewaySecret=value;}
    public String getGatewayKey(){return gatewayKey;}
    public void setGatewayKey(String value){gatewayKey=value;}
    public String getGatewayImage(){return gatewayImage;}
    public void setGatewayImage(String value){gatewayImage=value;}
    public boolean isEnabled(){return enabled;}
    public void setEnabled(boolean value){enabled=value;}
    public String getPython(){return python;}
    public void setPython(String value){python=value;}
    public String getInstaller(){return installer;}
    public void setInstaller(String value){installer=value;}
}
