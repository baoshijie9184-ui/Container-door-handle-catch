package com.ruanzhu.doorhandle.module.detection.security;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import org.springframework.security.core.Authentication;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

@Component
public class DetectionTaskAccessPolicy {

    public boolean isAdmin(Authentication authentication) {
        return authentication != null
                && authentication.isAuthenticated()
                && StringUtils.hasText(authentication.getName());
    }

    public void assertCanAccess(DetectionTask task, Authentication authentication) {
        assertAuthenticated(authentication);
    }

    public void assertAuthenticated(Authentication authentication) {
        if (!isAdmin(authentication)) {
            throw new BusinessException(401, "请先登录");
        }
    }
}
