package com.ruanzhu.doorhandle.contracts.agent;

import java.util.List;

public interface ResourceAgentReadApi {
    record DeviceView(String deviceCode, String status, String onlineStatus,
                      String plcStatus, String cameraStatus, String captureStatus) {}
    List<DeviceView> devices(AgentActor actor, int page, int size);
}
