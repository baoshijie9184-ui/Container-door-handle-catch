package com.ruanzhu.doorhandle.module.detection.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DuplicateTicketResolveRequest;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionDuplicateTicket;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionDuplicateTicketMapper;
import com.ruanzhu.doorhandle.module.detection.service.DetectionDuplicateTicketService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.time.LocalDateTime;
import java.util.List;

@Service
@RequiredArgsConstructor
public class DetectionDuplicateTicketServiceImpl implements DetectionDuplicateTicketService {
    private final DetectionDuplicateTicketMapper mapper;
    @Override public List<DetectionDuplicateTicket> listPending() { return mapper.findPending(); }
    @Override public DetectionDuplicateTicket detail(String ticketId) {
        return mapper.selectOne(new LambdaQueryWrapper<DetectionDuplicateTicket>().eq(DetectionDuplicateTicket::getTicketId, ticketId));
    }
    @Override @Transactional
    public DetectionDuplicateTicket resolve(String ticketId, DuplicateTicketResolveRequest request, String operator) {
        if (request == null || request.getExpectedVersion() == null || request.getExpectedVersion() < 0)
            throw new com.ruanzhu.doorhandle.common.BusinessException(400, "必须提供有效版本号");
        String resolution = request.getResolution() == null ? "" : request.getResolution().trim().toUpperCase(java.util.Locale.ROOT);
        if (!List.of("ACCEPT_LEFT", "ACCEPT_RIGHT", "REDETECT").contains(resolution))
            throw new com.ruanzhu.doorhandle.common.BusinessException(400, "不支持的处理结论");
        if (operator == null || operator.isBlank() || "anonymous".equals(operator))
            throw new com.ruanzhu.doorhandle.common.BusinessException(401, "请先登录");
        DetectionDuplicateTicket ticket = detail(ticketId);
        if (ticket == null) throw new com.ruanzhu.doorhandle.common.BusinessException(404, "重复工单不存在");
        if (ticket.getStatus() == null || !List.of("OPEN", "ASSIGNED", "COMPARING", "PENDING_APPROVAL").contains(ticket.getStatus())) throw new com.ruanzhu.doorhandle.common.BusinessException(409, "重复工单状态不可处理");
        if (!request.getExpectedVersion().equals(ticket.getVersion())) throw new com.ruanzhu.doorhandle.common.BusinessException(409, "重复工单已被其他主管更新，请刷新后重试");
        ticket.setResolution(request.getResolution().toUpperCase()); ticket.setComparisonResult(request.getComparisonResult());
        ticket.setStatus("RESOLVED"); ticket.setApprovedBy(operator); ticket.setApprovedAt(LocalDateTime.now()); ticket.setVersion(ticket.getVersion() + 1); ticket.setUpdatedAt(LocalDateTime.now());
        ticket.setResolution(resolution);
        if (mapper.resolveIfVersion(ticket, request.getExpectedVersion()) != 1)
            throw new com.ruanzhu.doorhandle.common.BusinessException(409, "重复工单已被更新，请刷新后重试");
        return ticket;
    }
}
