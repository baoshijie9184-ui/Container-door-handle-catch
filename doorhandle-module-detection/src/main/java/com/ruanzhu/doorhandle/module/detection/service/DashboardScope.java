package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy.SqlScope;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.Map;

/** Only for dashboard queries that return aggregate rows. */
public enum DashboardScope {
    ACCOUNT, COMPANY;

    public SqlScope forAggregate(DetectionTaskAccessPolicy access, String alias) {
        if (this == ACCOUNT) return access.currentSqlScope(alias);
        access.assertAuthenticated(SecurityContextHolder.getContext().getAuthentication());
        return new SqlScope("1 = 1", Map.of());
    }
}
