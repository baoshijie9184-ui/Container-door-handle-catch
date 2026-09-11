package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.module.detection.mapper.DetectionWorkUnitMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.security.authentication.AnonymousAuthenticationToken;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import java.util.LinkedHashMap;
import java.util.Map;

/** 工作单元概览：身份仅取自服务端认证上下文，不使用跨用户缓存。 */
@Service
@RequiredArgsConstructor
public class DetectionWorkloadDashboardService {
    private final DetectionWorkUnitMapper mapper;
    private final com.ruanzhu.doorhandle.module.detection.mapper.DetectionDuplicateTicketMapper duplicateMapper;

    public Map<String, Object> summary() {
        return summarize(false);
    }

    public Map<String, Object> duplicateSummary() {
        return summarize(true);
    }

    private Map<String, Object> summarize(boolean duplicates) {
        var authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !authentication.isAuthenticated()
                || authentication instanceof AnonymousAuthenticationToken) {
            throw new AccessDeniedException("请先登录");
        }
        var roles = authentication.getAuthorities().stream().map(a -> a.getAuthority()).toList();
        boolean supervisor = roles.contains("ROLE_SUPERVISOR") || roles.contains("ROLE_ADMIN");
        if (!supervisor && !roles.contains("ROLE_INSPECTOR")) {
            throw new AccessDeniedException("无权查看检测工作量");
        }
        var rows = duplicates
                ? (supervisor ? duplicateMapper.countDepartmentStatuses() : duplicateMapper.countAssignedStatuses(authentication.getName()))
                : (supervisor ? mapper.countDepartmentStatuses() : mapper.countAssignedStatuses(authentication.getName()));
        Map<String, Long> counts = new LinkedHashMap<>();
        var statuses = duplicates ? java.util.List.of("OPEN", "ASSIGNED", "COMPARING", "PENDING_APPROVAL")
                : java.util.List.of("WAITING", "ASSIGNED", "PROCESSING", "SUBMITTED");
        for (String status : statuses) {
            counts.put(status, 0L);
        }
        for (var row : rows) {
            String status = String.valueOf(row.get("status"));
            if (counts.containsKey(status)) counts.put(status, ((Number) row.get("total")).longValue());
        }
        return Map.of("scope", supervisor ? "DEPARTMENT" : "MINE",
                "counts", counts, "unit", duplicates ? "复查工单" : "工作单元",
                "activeCount", counts.values().stream().mapToLong(Long::longValue).sum());
    }
}
