package com.ruanzhu.doorhandle.framework.persistence.workflow;

import java.time.LocalDate;
import java.time.LocalDateTime;

public record WorkflowTiming(LocalDate effectiveDate, LocalDateTime scheduledFor) { }
