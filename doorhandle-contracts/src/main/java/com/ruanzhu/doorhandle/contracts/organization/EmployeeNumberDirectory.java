package com.ruanzhu.doorhandle.contracts.organization;

import java.util.Collection;
import java.util.List;

/** Personnel numbers also exist for staff without an application login. */
public interface EmployeeNumberDirectory {
    record EmployeeLabel(String employeeNumber, String name) {}
    List<EmployeeLabel> findByNumbers(Collection<String> numbers);
}
