package com.ruanzhu.doorhandle.contracts.security;

import java.util.List;

/** 质检责任人采用登录账号；不向检测模块返回账号凭证或联系方式。 */
public interface QualityAssigneeDirectory {
    record Option(String username,Long userId,String revision) {
        public Option(String username){this(username,null,null);}
    }
    List<Option> search(String keyword);
    boolean exists(String username);
}
