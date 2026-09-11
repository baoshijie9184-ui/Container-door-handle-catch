package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.module.detection.dto.detection.DuplicateTicketResolveRequest;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionDuplicateTicket;
import java.util.List;

public interface DetectionDuplicateTicketService {
    List<DetectionDuplicateTicket> listPending();
    DetectionDuplicateTicket detail(String ticketId);
    DetectionDuplicateTicket resolve(String ticketId, DuplicateTicketResolveRequest request, String operator);
}
