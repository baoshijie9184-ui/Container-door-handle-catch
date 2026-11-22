package com.ruanzhu.doorhandle.contracts.security;

/** 业务写操作重新核对账号；身份只能由服务端认证上下文传入。 */
public interface BusinessUserDirectory {
    record Identity(long userId, String username, boolean supervisor) {}
    /** The personnel directory owns the canonical employee number of an account. */
    default String employeeNumber(long userId) { throw new IllegalStateException("当前账号未接入人员名册"); }
    Identity current(long userId, String username);
    /** Refresh and retain the actual actor role for a sensitive business transaction. */
    default Identity lockCurrent(long userId, String username) { throw new SecurityException("业务身份确认锁未接入"); }
    /** Require a current inspector account bound to an active detection employee. */
    default void lockDetectionEmployee(long userId, String username) { throw new SecurityException("检测员工资格确认未接入"); }
    /** Return the current detection employee ID under the account and personnel locks. */
    default long lockDetectionEmployeeId(long userId, String username) { throw new SecurityException("检测员工关联未接入"); }
    /** Resolve only a trusted server principal with its stable user ID, never a name supplied by a client. */
    default Identity authenticated() { throw new SecurityException("当前业务身份未接入"); }
}
