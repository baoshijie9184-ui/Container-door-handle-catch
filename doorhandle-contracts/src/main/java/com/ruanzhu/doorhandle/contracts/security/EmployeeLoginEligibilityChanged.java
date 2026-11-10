package com.ruanzhu.doorhandle.contracts.security;

/** Personnel owns this event; system resolves current account bindings inside the same transaction. */
public record EmployeeLoginEligibilityChanged(long employeeId) {
    public EmployeeLoginEligibilityChanged {
        if(employeeId<=0)throw new IllegalArgumentException("employeeId must be positive");
    }
}
