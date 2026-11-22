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

    public SqlScope forCompletedResults(DetectionTaskAccessPolicy access, String alias) {
        var scope = forAggregate(access, alias);
        String folderScope = this == ACCOUNT ? access.currentSqlScope("f.").predicate() : "1=1";
        return new SqlScope(scope.predicate() + " AND " + BusinessDetectionTasks.completedResultFilter(alias, folderScope),
                scope.parameters());
    }

    public SqlScope forCompletedCollections(DetectionTaskAccessPolicy access, String alias) {
        var scope = forAggregate(access, alias);
        String uploadScope = this == ACCOUNT ? access.currentSqlScope("o.").predicate() : "1=1";
        return new SqlScope(scope.predicate() + " AND " + BusinessDetectionTasks.completedCollectionFilter(alias, uploadScope),
                scope.parameters());
    }

    public SqlScope forVerification(DetectionTaskAccessPolicy access, String alias) {
        var scope = forAggregate(access, alias);
        return new SqlScope(scope.predicate() + " AND " + BusinessDetectionTasks.verificationTaskFilter(alias),
                scope.parameters());
    }
}
