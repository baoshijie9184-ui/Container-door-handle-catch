package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.common.Result;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DuplicateTicketResolveRequest;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionDuplicateTicket;
import com.ruanzhu.doorhandle.module.detection.service.DetectionDuplicateTicketService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.security.access.prepost.PreAuthorize;
import java.util.List;

@RestController
@RequestMapping("/api/detection/supervisor/duplicate-tickets")
@RequiredArgsConstructor
public class DetectionDuplicateTicketController {
    private final DetectionDuplicateTicketService service;
    @GetMapping @PreAuthorize("hasAnyRole('SUPERVISOR','ADMIN')")
    public Result<List<DetectionDuplicateTicket>> list() { return Result.success(service.listPending()); }
    @GetMapping("/{ticketId}") @PreAuthorize("hasAnyRole('SUPERVISOR','ADMIN')")
    public Result<DetectionDuplicateTicket> detail(@PathVariable String ticketId) { return Result.success(service.detail(ticketId)); }
    @PostMapping("/{ticketId}/resolve")
    @PreAuthorize("hasAnyRole('SUPERVISOR','ADMIN')")
    public Result<DetectionDuplicateTicket> resolve(@PathVariable String ticketId, @Valid @RequestBody DuplicateTicketResolveRequest request, Authentication authentication) {
        return Result.success(service.resolve(ticketId, request, authentication == null ? "anonymous" : authentication.getName()));
    }
}
