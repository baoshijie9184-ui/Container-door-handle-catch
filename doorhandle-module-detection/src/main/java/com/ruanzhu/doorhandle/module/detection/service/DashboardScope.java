package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy.SqlScope;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.Map;

/** Only for dashboard queries that return aggregate rows. */
public enum DashboardScope {
    ACCOUNT, COMPANY;

    public SqlScope forAggregate(DetectionTaskAccessPolicy access, String alias) {
        String formal = BusinessDetectionTasks.filter(alias);
        if (this == ACCOUNT) {
            var account = access.currentSqlScope(alias);
            return new SqlScope(formal + " AND (" + account.predicate() + ")", account.parameters());
        }
        access.assertAuthenticated(SecurityContextHolder.getContext().getAuthentication());
        return new SqlScope(formal, Map.of());
    }
}
