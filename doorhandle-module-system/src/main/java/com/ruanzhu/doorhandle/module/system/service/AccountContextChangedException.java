package com.ruanzhu.doorhandle.module.system.service;

public class AccountContextChangedException extends RuntimeException {
    public AccountContextChangedException(){super("账号上下文已变化，请重新读取当前身份");}
}
