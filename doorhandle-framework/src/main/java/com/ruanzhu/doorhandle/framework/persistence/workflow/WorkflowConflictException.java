package com.ruanzhu.doorhandle.framework.persistence.workflow;

public final class WorkflowConflictException extends IllegalStateException {
    public WorkflowConflictException(String message) { super(message); }
}
