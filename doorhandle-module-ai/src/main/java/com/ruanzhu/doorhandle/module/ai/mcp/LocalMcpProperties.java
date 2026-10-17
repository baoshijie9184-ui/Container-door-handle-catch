package com.ruanzhu.doorhandle.module.ai.mcp;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix="agentscope.mcp")
public class LocalMcpProperties {
    private boolean enabled;
    private boolean durableInstallEnabled;
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
