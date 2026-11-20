package com.ruanzhu.doorhandle.contracts.organization;

import java.util.Collection;
import java.util.List;

/** Bound employee numbers for displaying the authors of business records. */
public interface EmployeeAccountNumbers {
    record BoundAccount(long userId, String username, EmployeeNumberDirectory.EmployeeLabel employee) {}
    List<BoundAccount> resolve(Collection<Long> ids, Collection<String> usernames);
}
