package com.ruanzhu.doorhandle.module.ai.mcp;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix="agentscope.mcp")
public class LocalMcpProperties {
    private boolean enabled;
    private String python="python";
    private String installer="${user.dir}/script/shell/install-local-fetch-mcp.py";
    public boolean isEnabled(){return enabled;}
    public void setEnabled(boolean value){enabled=value;}
    public String getPython(){return python;}
    public void setPython(String value){python=value;}
    public String getInstaller(){return installer;}
    public void setInstaller(String value){installer=value;}
}
