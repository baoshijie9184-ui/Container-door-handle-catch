package com.ruanzhu.doorhandle.module.ai.mcp;

import java.net.*;
import java.util.*;

/** 限定公开 HTTP 页面；服务端仍检查每次重定向的目标地址。 */
public final class FetchUrlPolicy {
    private FetchUrlPolicy(){}
    public static String validate(Object value){
        if(!(value instanceof String text)||text.length()>2048||text.chars().anyMatch(Character::isISOControl))throw new IllegalArgumentException("网页地址不合法");
        try{var uri=URI.create(text);String host=uri.getHost();
            if(!Set.of("https","http").contains(uri.getScheme())||host==null||uri.getUserInfo()!=null||uri.getFragment()!=null||uri.getPort()!=-1&&uri.getPort()!=80&&uri.getPort()!=443||!host.contains(".")||host.toLowerCase(Locale.ROOT).endsWith(".local"))throw new IllegalArgumentException();
            if(uri.getRawQuery()!=null&&uri.getRawQuery().matches("(?i).*(token|api[_-]?key|authorization|password|secret)=.*"))throw new IllegalArgumentException();
            for(var address:InetAddress.getAllByName(host))if(!publicAddress(address))throw new IllegalArgumentException();
            return text;
        }catch(Exception e){throw new IllegalArgumentException("仅允许不含凭证的公开 HTTP/HTTPS 网页");}
    }
    static boolean publicAddress(InetAddress address){
        if(address.isAnyLocalAddress()||address.isLoopbackAddress()||address.isLinkLocalAddress()||address.isSiteLocalAddress()||address.isMulticastAddress())return false;
        byte[] b=address.getAddress();int first=b[0]&255;
        if(b.length==16)return first!=0xfc&&first!=0xfd;
        int second=b[1]&255,third=b[2]&255;
        return first!=0&&first<224&&!(first==100&&second>=64&&second<=127)&&!(first==192&&second==0)&&!(first==198&&(second==18||second==19))&&!(first==198&&second==51&&third==100)&&!(first==203&&second==0&&third==113);
    }
}
