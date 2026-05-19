import{a as Fp,g as $p,r as fl,j as E,R as Ip,G as Pp}from"./hakit-B0mgNB9o.js";import{r as am}from"./vendor-CVL8XC6B.js";(function(){const D=document.createElement("link").relList;if(D&&D.supports&&D.supports("modulepreload"))return;for(const U of document.querySelectorAll('link[rel="modulepreload"]'))f(U);new MutationObserver(U=>{for(const C of U)if(C.type==="childList")for(const Sa of C.addedNodes)Sa.tagName==="LINK"&&Sa.rel==="modulepreload"&&f(Sa)}).observe(document,{childList:!0,subtree:!0});function N(U){const C={};return U.integrity&&(C.integrity=U.integrity),U.referrerPolicy&&(C.referrerPolicy=U.referrerPolicy),U.crossOrigin==="use-credentials"?C.credentials="include":U.crossOrigin==="anonymous"?C.credentials="omit":C.credentials="same-origin",C}function f(U){if(U.ep)return;U.ep=!0;const C=N(U);fetch(U.href,C)}})();var tu={exports:{}},pt={},eu={exports:{}},iu={};/**
 * @license React
 * scheduler.production.js
 *
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */var rr;function lm(){return rr||(rr=1,(function(S){function D(h,x){var M=h.length;h.push(x);a:for(;0<M;){var F=M-1>>>1,$=h[F];if(0<U($,x))h[F]=x,h[M]=$,M=F;else break a}}function N(h){return h.length===0?null:h[0]}function f(h){if(h.length===0)return null;var x=h[0],M=h.pop();if(M!==x){h[0]=M;a:for(var F=0,$=h.length,xa=$>>>1;F<xa;){var la=2*(F+1)-1,L=h[la],ra=la+1,ul=h[ra];if(0>U(L,M))ra<$&&0>U(ul,L)?(h[F]=ul,h[ra]=M,F=ra):(h[F]=L,h[la]=M,F=la);else if(ra<$&&0>U(ul,M))h[F]=ul,h[ra]=M,F=ra;else break a}}return x}function U(h,x){var M=h.sortIndex-x.sortIndex;return M!==0?M:h.id-x.id}if(S.unstable_now=void 0,typeof performance=="object"&&typeof performance.now=="function"){var C=performance;S.unstable_now=function(){return C.now()}}else{var Sa=Date,il=Sa.now();S.unstable_now=function(){return Sa.now()-il}}var Aa=[],Ya=[],Ds=1,k=null,va=3,Hl=!1,ll=!1,Za=!1,Bs=!1,Us=typeof setTimeout=="function"?setTimeout:null,Sn=typeof clearTimeout=="function"?clearTimeout:null,La=typeof setImmediate<"u"?setImmediate:null;function _l(h){for(var x=N(Ya);x!==null;){if(x.callback===null)f(Ya);else if(x.startTime<=h)f(Ya),x.sortIndex=x.expirationTime,D(Aa,x);else break;x=N(Ya)}}function ds(h){if(Za=!1,_l(h),!ll)if(N(Aa)!==null)ll=!0,cl||(cl=!0,Qa());else{var x=N(Ya);x!==null&&ml(ds,x.startTime-h)}}var cl=!1,pl=-1,sl=5,ks=-1;function mt(){return Bs?!0:!(S.unstable_now()-ks<sl)}function Cs(){if(Bs=!1,cl){var h=S.unstable_now();ks=h;var x=!0;try{a:{ll=!1,Za&&(Za=!1,Sn(pl),pl=-1),Hl=!0;var M=va;try{l:{for(_l(h),k=N(Aa);k!==null&&!(k.expirationTime>h&&mt());){var F=k.callback;if(typeof F=="function"){k.callback=null,va=k.priorityLevel;var $=F(k.expirationTime<=h);if(h=S.unstable_now(),typeof $=="function"){k.callback=$,_l(h),x=!0;break l}k===N(Aa)&&f(Aa),_l(h)}else f(Aa);k=N(Aa)}if(k!==null)x=!0;else{var xa=N(Ya);xa!==null&&ml(ds,xa.startTime-h),x=!1}}break a}finally{k=null,va=M,Hl=!1}x=void 0}}finally{x?Qa():cl=!1}}}var Qa;if(typeof La=="function")Qa=function(){La(Cs)};else if(typeof MessageChannel<"u"){var gt=new MessageChannel,xn=gt.port2;gt.port1.onmessage=Cs,Qa=function(){xn.postMessage(null)}}else Qa=function(){Us(Cs,0)};function ml(h,x){pl=Us(function(){h(S.unstable_now())},x)}S.unstable_IdlePriority=5,S.unstable_ImmediatePriority=1,S.unstable_LowPriority=4,S.unstable_NormalPriority=3,S.unstable_Profiling=null,S.unstable_UserBlockingPriority=2,S.unstable_cancelCallback=function(h){h.callback=null},S.unstable_forceFrameRate=function(h){0>h||125<h?console.error("forceFrameRate takes a positive int between 0 and 125, forcing frame rates higher than 125 fps is not supported"):sl=0<h?Math.floor(1e3/h):5},S.unstable_getCurrentPriorityLevel=function(){return va},S.unstable_next=function(h){switch(va){case 1:case 2:case 3:var x=3;break;default:x=va}var M=va;va=x;try{return h()}finally{va=M}},S.unstable_requestPaint=function(){Bs=!0},S.unstable_runWithPriority=function(h,x){switch(h){case 1:case 2:case 3:case 4:case 5:break;default:h=3}var M=va;va=h;try{return x()}finally{va=M}},S.unstable_scheduleCallback=function(h,x,M){var F=S.unstable_now();switch(typeof M=="object"&&M!==null?(M=M.delay,M=typeof M=="number"&&0<M?F+M:F):M=F,h){case 1:var $=-1;break;case 2:$=250;break;case 5:$=1073741823;break;case 4:$=1e4;break;default:$=5e3}return $=M+$,h={id:Ds++,callback:x,priorityLevel:h,startTime:M,expirationTime:$,sortIndex:-1},M>F?(h.sortIndex=M,D(Ya,h),N(Aa)===null&&h===N(Ya)&&(Za?(Sn(pl),pl=-1):Za=!0,ml(ds,M-F))):(h.sortIndex=$,D(Aa,h),ll||Hl||(ll=!0,cl||(cl=!0,Qa()))),h},S.unstable_shouldYield=mt,S.unstable_wrapCallback=function(h){var x=va;return function(){var M=va;va=x;try{return h.apply(this,arguments)}finally{va=M}}}})(iu)),iu}var fr;function sm(){return fr||(fr=1,eu.exports=lm()),eu.exports}/**
 * @license React
 * react-dom-client.production.js
 *
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */var pr;function nm(){if(pr)return pt;pr=1;var S=sm(),D=Fp(),N=am();function f(a){var l="https://react.dev/errors/"+a;if(1<arguments.length){l+="?args[]="+encodeURIComponent(arguments[1]);for(var s=2;s<arguments.length;s++)l+="&args[]="+encodeURIComponent(arguments[s])}return"Minified React error #"+a+"; visit "+l+" for the full message or use the non-minified dev environment for full errors and additional helpful warnings."}function U(a){return!(!a||a.nodeType!==1&&a.nodeType!==9&&a.nodeType!==11)}function C(a){var l=a,s=a;if(a.alternate)for(;l.return;)l=l.return;else{a=l;do l=a,(l.flags&4098)!==0&&(s=l.return),a=l.return;while(a)}return l.tag===3?s:null}function Sa(a){if(a.tag===13){var l=a.memoizedState;if(l===null&&(a=a.alternate,a!==null&&(l=a.memoizedState)),l!==null)return l.dehydrated}return null}function il(a){if(a.tag===31){var l=a.memoizedState;if(l===null&&(a=a.alternate,a!==null&&(l=a.memoizedState)),l!==null)return l.dehydrated}return null}function Aa(a){if(C(a)!==a)throw Error(f(188))}function Ya(a){var l=a.alternate;if(!l){if(l=C(a),l===null)throw Error(f(188));return l!==a?null:a}for(var s=a,n=l;;){var t=s.return;if(t===null)break;var e=t.alternate;if(e===null){if(n=t.return,n!==null){s=n;continue}break}if(t.child===e.child){for(e=t.child;e;){if(e===s)return Aa(t),a;if(e===n)return Aa(t),l;e=e.sibling}throw Error(f(188))}if(s.return!==n.return)s=t,n=e;else{for(var i=!1,c=t.child;c;){if(c===s){i=!0,s=t,n=e;break}if(c===n){i=!0,n=t,s=e;break}c=c.sibling}if(!i){for(c=e.child;c;){if(c===s){i=!0,s=e,n=t;break}if(c===n){i=!0,n=e,s=t;break}c=c.sibling}if(!i)throw Error(f(189))}}if(s.alternate!==n)throw Error(f(190))}if(s.tag!==3)throw Error(f(188));return s.stateNode.current===s?a:l}function Ds(a){var l=a.tag;if(l===5||l===26||l===27||l===6)return a;for(a=a.child;a!==null;){if(l=Ds(a),l!==null)return l;a=a.sibling}return null}var k=Object.assign,va=Symbol.for("react.element"),Hl=Symbol.for("react.transitional.element"),ll=Symbol.for("react.portal"),Za=Symbol.for("react.fragment"),Bs=Symbol.for("react.strict_mode"),Us=Symbol.for("react.profiler"),Sn=Symbol.for("react.consumer"),La=Symbol.for("react.context"),_l=Symbol.for("react.forward_ref"),ds=Symbol.for("react.suspense"),cl=Symbol.for("react.suspense_list"),pl=Symbol.for("react.memo"),sl=Symbol.for("react.lazy"),ks=Symbol.for("react.activity"),mt=Symbol.for("react.memo_cache_sentinel"),Cs=Symbol.iterator;function Qa(a){return a===null||typeof a!="object"?null:(a=Cs&&a[Cs]||a["@@iterator"],typeof a=="function"?a:null)}var gt=Symbol.for("react.client.reference");function xn(a){if(a==null)return null;if(typeof a=="function")return a.$$typeof===gt?null:a.displayName||a.name||null;if(typeof a=="string")return a;switch(a){case Za:return"Fragment";case Us:return"Profiler";case Bs:return"StrictMode";case ds:return"Suspense";case cl:return"SuspenseList";case ks:return"Activity"}if(typeof a=="object")switch(a.$$typeof){case ll:return"Portal";case La:return a.displayName||"Context";case Sn:return(a._context.displayName||"Context")+".Consumer";case _l:var l=a.render;return a=a.displayName,a||(a=l.displayName||l.name||"",a=a!==""?"ForwardRef("+a+")":"ForwardRef"),a;case pl:return l=a.displayName||null,l!==null?l:xn(a.type)||"Memo";case sl:l=a._payload,a=a._init;try{return xn(a(l))}catch{}}return null}var ml=Array.isArray,h=D.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE,x=N.__DOM_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE,M={pending:!1,data:null,method:null,action:null},F=[],$=-1;function xa(a){return{current:a}}function la(a){0>$||(a.current=F[$],F[$]=null,$--)}function L(a,l){$++,F[$]=a.current,a.current=l}var ra=xa(null),ul=xa(null),Nl=xa(null),bt=xa(null);function ht(a,l){switch(L(Nl,l),L(ul,a),L(ra,null),l.nodeType){case 9:case 11:a=(a=l.documentElement)&&(a=a.namespaceURI)?_v(a):0;break;default:if(a=l.tagName,l=l.namespaceURI)l=_v(l),a=Nv(l,a);else switch(a){case"svg":a=1;break;case"math":a=2;break;default:a=0}}la(ra),L(ra,a)}function Hs(){la(ra),la(ul),la(Nl)}function qe(a){a.memoizedState!==null&&L(bt,a);var l=ra.current,s=Nv(l,a.type);l!==s&&(L(ul,a),L(ra,s))}function yt(a){ul.current===a&&(la(ra),la(ul)),bt.current===a&&(la(bt),ot._currentValue=M)}var Ge,ou;function os(a){if(Ge===void 0)try{throw Error()}catch(s){var l=s.stack.trim().match(/\n( *(at )?)/);Ge=l&&l[1]||"",ou=-1<s.stack.indexOf(`
    at`)?" (<anonymous>)":-1<s.stack.indexOf("@")?"@unknown:0:0":""}return`
`+Ge+a+ou}var Ye=!1;function Ze(a,l){if(!a||Ye)return"";Ye=!0;var s=Error.prepareStackTrace;Error.prepareStackTrace=void 0;try{var n={DetermineComponentFrameRoot:function(){try{if(l){var y=function(){throw Error()};if(Object.defineProperty(y.prototype,"props",{set:function(){throw Error()}}),typeof Reflect=="object"&&Reflect.construct){try{Reflect.construct(y,[])}catch(m){var p=m}Reflect.construct(a,[],y)}else{try{y.call()}catch(m){p=m}a.call(y.prototype)}}else{try{throw Error()}catch(m){p=m}(y=a())&&typeof y.catch=="function"&&y.catch(function(){})}}catch(m){if(m&&p&&typeof m.stack=="string")return[m.stack,p.stack]}return[null,null]}};n.DetermineComponentFrameRoot.displayName="DetermineComponentFrameRoot";var t=Object.getOwnPropertyDescriptor(n.DetermineComponentFrameRoot,"name");t&&t.configurable&&Object.defineProperty(n.DetermineComponentFrameRoot,"name",{value:"DetermineComponentFrameRoot"});var e=n.DetermineComponentFrameRoot(),i=e[0],c=e[1];if(i&&c){var u=i.split(`
`),r=c.split(`
`);for(t=n=0;n<u.length&&!u[n].includes("DetermineComponentFrameRoot");)n++;for(;t<r.length&&!r[t].includes("DetermineComponentFrameRoot");)t++;if(n===u.length||t===r.length)for(n=u.length-1,t=r.length-1;1<=n&&0<=t&&u[n]!==r[t];)t--;for(;1<=n&&0<=t;n--,t--)if(u[n]!==r[t]){if(n!==1||t!==1)do if(n--,t--,0>t||u[n]!==r[t]){var g=`
`+u[n].replace(" at new "," at ");return a.displayName&&g.includes("<anonymous>")&&(g=g.replace("<anonymous>",a.displayName)),g}while(1<=n&&0<=t);break}}}finally{Ye=!1,Error.prepareStackTrace=s}return(s=a?a.displayName||a.name:"")?os(s):""}function Mr(a,l){switch(a.tag){case 26:case 27:case 5:return os(a.type);case 16:return os("Lazy");case 13:return a.child!==l&&l!==null?os("Suspense Fallback"):os("Suspense");case 19:return os("SuspenseList");case 0:case 15:return Ze(a.type,!1);case 11:return Ze(a.type.render,!1);case 1:return Ze(a.type,!0);case 31:return os("Activity");default:return""}}function vu(a){try{var l="",s=null;do l+=Mr(a,s),s=a,a=a.return;while(a);return l}catch(n){return`
Error generating stack: `+n.message+`
`+n.stack}}var Le=Object.prototype.hasOwnProperty,Qe=S.unstable_scheduleCallback,Xe=S.unstable_cancelCallback,Er=S.unstable_shouldYield,Or=S.unstable_requestPaint,Ua=S.unstable_now,Dr=S.unstable_getCurrentPriorityLevel,ru=S.unstable_ImmediatePriority,fu=S.unstable_UserBlockingPriority,St=S.unstable_NormalPriority,Br=S.unstable_LowPriority,pu=S.unstable_IdlePriority,Ur=S.log,kr=S.unstable_setDisableYieldValue,zn=null,ka=null;function Rl(a){if(typeof Ur=="function"&&kr(a),ka&&typeof ka.setStrictMode=="function")try{ka.setStrictMode(zn,a)}catch{}}var Ca=Math.clz32?Math.clz32:_r,Cr=Math.log,Hr=Math.LN2;function _r(a){return a>>>=0,a===0?32:31-(Cr(a)/Hr|0)|0}var xt=256,zt=262144,At=4194304;function vs(a){var l=a&42;if(l!==0)return l;switch(a&-a){case 1:return 1;case 2:return 2;case 4:return 4;case 8:return 8;case 16:return 16;case 32:return 32;case 64:return 64;case 128:return 128;case 256:case 512:case 1024:case 2048:case 4096:case 8192:case 16384:case 32768:case 65536:case 131072:return a&261888;case 262144:case 524288:case 1048576:case 2097152:return a&3932160;case 4194304:case 8388608:case 16777216:case 33554432:return a&62914560;case 67108864:return 67108864;case 134217728:return 134217728;case 268435456:return 268435456;case 536870912:return 536870912;case 1073741824:return 0;default:return a}}function wt(a,l,s){var n=a.pendingLanes;if(n===0)return 0;var t=0,e=a.suspendedLanes,i=a.pingedLanes;a=a.warmLanes;var c=n&134217727;return c!==0?(n=c&~e,n!==0?t=vs(n):(i&=c,i!==0?t=vs(i):s||(s=c&~a,s!==0&&(t=vs(s))))):(c=n&~e,c!==0?t=vs(c):i!==0?t=vs(i):s||(s=n&~a,s!==0&&(t=vs(s)))),t===0?0:l!==0&&l!==t&&(l&e)===0&&(e=t&-t,s=l&-l,e>=s||e===32&&(s&4194048)!==0)?l:t}function An(a,l){return(a.pendingLanes&~(a.suspendedLanes&~a.pingedLanes)&l)===0}function Nr(a,l){switch(a){case 1:case 2:case 4:case 8:case 64:return l+250;case 16:case 32:case 128:case 256:case 512:case 1024:case 2048:case 4096:case 8192:case 16384:case 32768:case 65536:case 131072:case 262144:case 524288:case 1048576:case 2097152:return l+5e3;case 4194304:case 8388608:case 16777216:case 33554432:return-1;case 67108864:case 134217728:case 268435456:case 536870912:case 1073741824:return-1;default:return-1}}function mu(){var a=At;return At<<=1,(At&62914560)===0&&(At=4194304),a}function Ve(a){for(var l=[],s=0;31>s;s++)l.push(a);return l}function wn(a,l){a.pendingLanes|=l,l!==268435456&&(a.suspendedLanes=0,a.pingedLanes=0,a.warmLanes=0)}function Rr(a,l,s,n,t,e){var i=a.pendingLanes;a.pendingLanes=s,a.suspendedLanes=0,a.pingedLanes=0,a.warmLanes=0,a.expiredLanes&=s,a.entangledLanes&=s,a.errorRecoveryDisabledLanes&=s,a.shellSuspendCounter=0;var c=a.entanglements,u=a.expirationTimes,r=a.hiddenUpdates;for(s=i&~s;0<s;){var g=31-Ca(s),y=1<<g;c[g]=0,u[g]=-1;var p=r[g];if(p!==null)for(r[g]=null,g=0;g<p.length;g++){var m=p[g];m!==null&&(m.lane&=-536870913)}s&=~y}n!==0&&gu(a,n,0),e!==0&&t===0&&a.tag!==0&&(a.suspendedLanes|=e&~(i&~l))}function gu(a,l,s){a.pendingLanes|=l,a.suspendedLanes&=~l;var n=31-Ca(l);a.entangledLanes|=l,a.entanglements[n]=a.entanglements[n]|1073741824|s&261930}function bu(a,l){var s=a.entangledLanes|=l;for(a=a.entanglements;s;){var n=31-Ca(s),t=1<<n;t&l|a[n]&l&&(a[n]|=l),s&=~t}}function hu(a,l){var s=l&-l;return s=(s&42)!==0?1:Ke(s),(s&(a.suspendedLanes|l))!==0?0:s}function Ke(a){switch(a){case 2:a=1;break;case 8:a=4;break;case 32:a=16;break;case 256:case 512:case 1024:case 2048:case 4096:case 8192:case 16384:case 32768:case 65536:case 131072:case 262144:case 524288:case 1048576:case 2097152:case 4194304:case 8388608:case 16777216:case 33554432:a=128;break;case 268435456:a=134217728;break;default:a=0}return a}function Je(a){return a&=-a,2<a?8<a?(a&134217727)!==0?32:268435456:8:2}function yu(){var a=x.p;return a!==0?a:(a=window.event,a===void 0?32:er(a.type))}function Su(a,l){var s=x.p;try{return x.p=a,l()}finally{x.p=s}}var jl=Math.random().toString(36).slice(2),ma="__reactFiber$"+jl,wa="__reactProps$"+jl,_s="__reactContainer$"+jl,We="__reactEvents$"+jl,jr="__reactListeners$"+jl,qr="__reactHandles$"+jl,xu="__reactResources$"+jl,Tn="__reactMarker$"+jl;function Fe(a){delete a[ma],delete a[wa],delete a[We],delete a[jr],delete a[qr]}function Ns(a){var l=a[ma];if(l)return l;for(var s=a.parentNode;s;){if(l=s[_s]||s[ma]){if(s=l.alternate,l.child!==null||s!==null&&s.child!==null)for(a=Lv(a);a!==null;){if(s=a[ma])return s;a=Lv(a)}return l}a=s,s=a.parentNode}return null}function Rs(a){if(a=a[ma]||a[_s]){var l=a.tag;if(l===5||l===6||l===13||l===31||l===26||l===27||l===3)return a}return null}function Mn(a){var l=a.tag;if(l===5||l===26||l===27||l===6)return a.stateNode;throw Error(f(33))}function js(a){var l=a[xu];return l||(l=a[xu]={hoistableStyles:new Map,hoistableScripts:new Map}),l}function fa(a){a[Tn]=!0}var zu=new Set,Au={};function rs(a,l){qs(a,l),qs(a+"Capture",l)}function qs(a,l){for(Au[a]=l,a=0;a<l.length;a++)zu.add(l[a])}var Gr=RegExp("^[:A-Z_a-z\\u00C0-\\u00D6\\u00D8-\\u00F6\\u00F8-\\u02FF\\u0370-\\u037D\\u037F-\\u1FFF\\u200C-\\u200D\\u2070-\\u218F\\u2C00-\\u2FEF\\u3001-\\uD7FF\\uF900-\\uFDCF\\uFDF0-\\uFFFD][:A-Z_a-z\\u00C0-\\u00D6\\u00D8-\\u00F6\\u00F8-\\u02FF\\u0370-\\u037D\\u037F-\\u1FFF\\u200C-\\u200D\\u2070-\\u218F\\u2C00-\\u2FEF\\u3001-\\uD7FF\\uF900-\\uFDCF\\uFDF0-\\uFFFD\\-.0-9\\u00B7\\u0300-\\u036F\\u203F-\\u2040]*$"),wu={},Tu={};function Yr(a){return Le.call(Tu,a)?!0:Le.call(wu,a)?!1:Gr.test(a)?Tu[a]=!0:(wu[a]=!0,!1)}function Tt(a,l,s){if(Yr(l))if(s===null)a.removeAttribute(l);else{switch(typeof s){case"undefined":case"function":case"symbol":a.removeAttribute(l);return;case"boolean":var n=l.toLowerCase().slice(0,5);if(n!=="data-"&&n!=="aria-"){a.removeAttribute(l);return}}a.setAttribute(l,""+s)}}function Mt(a,l,s){if(s===null)a.removeAttribute(l);else{switch(typeof s){case"undefined":case"function":case"symbol":case"boolean":a.removeAttribute(l);return}a.setAttribute(l,""+s)}}function gl(a,l,s,n){if(n===null)a.removeAttribute(s);else{switch(typeof n){case"undefined":case"function":case"symbol":case"boolean":a.removeAttribute(s);return}a.setAttributeNS(l,s,""+n)}}function Xa(a){switch(typeof a){case"bigint":case"boolean":case"number":case"string":case"undefined":return a;case"object":return a;default:return""}}function Mu(a){var l=a.type;return(a=a.nodeName)&&a.toLowerCase()==="input"&&(l==="checkbox"||l==="radio")}function Zr(a,l,s){var n=Object.getOwnPropertyDescriptor(a.constructor.prototype,l);if(!a.hasOwnProperty(l)&&typeof n<"u"&&typeof n.get=="function"&&typeof n.set=="function"){var t=n.get,e=n.set;return Object.defineProperty(a,l,{configurable:!0,get:function(){return t.call(this)},set:function(i){s=""+i,e.call(this,i)}}),Object.defineProperty(a,l,{enumerable:n.enumerable}),{getValue:function(){return s},setValue:function(i){s=""+i},stopTracking:function(){a._valueTracker=null,delete a[l]}}}}function $e(a){if(!a._valueTracker){var l=Mu(a)?"checked":"value";a._valueTracker=Zr(a,l,""+a[l])}}function Eu(a){if(!a)return!1;var l=a._valueTracker;if(!l)return!0;var s=l.getValue(),n="";return a&&(n=Mu(a)?a.checked?"true":"false":a.value),a=n,a!==s?(l.setValue(a),!0):!1}function Et(a){if(a=a||(typeof document<"u"?document:void 0),typeof a>"u")return null;try{return a.activeElement||a.body}catch{return a.body}}var Lr=/[\n"\\]/g;function Va(a){return a.replace(Lr,function(l){return"\\"+l.charCodeAt(0).toString(16)+" "})}function Ie(a,l,s,n,t,e,i,c){a.name="",i!=null&&typeof i!="function"&&typeof i!="symbol"&&typeof i!="boolean"?a.type=i:a.removeAttribute("type"),l!=null?i==="number"?(l===0&&a.value===""||a.value!=l)&&(a.value=""+Xa(l)):a.value!==""+Xa(l)&&(a.value=""+Xa(l)):i!=="submit"&&i!=="reset"||a.removeAttribute("value"),l!=null?Pe(a,i,Xa(l)):s!=null?Pe(a,i,Xa(s)):n!=null&&a.removeAttribute("value"),t==null&&e!=null&&(a.defaultChecked=!!e),t!=null&&(a.checked=t&&typeof t!="function"&&typeof t!="symbol"),c!=null&&typeof c!="function"&&typeof c!="symbol"&&typeof c!="boolean"?a.name=""+Xa(c):a.removeAttribute("name")}function Ou(a,l,s,n,t,e,i,c){if(e!=null&&typeof e!="function"&&typeof e!="symbol"&&typeof e!="boolean"&&(a.type=e),l!=null||s!=null){if(!(e!=="submit"&&e!=="reset"||l!=null)){$e(a);return}s=s!=null?""+Xa(s):"",l=l!=null?""+Xa(l):s,c||l===a.value||(a.value=l),a.defaultValue=l}n=n??t,n=typeof n!="function"&&typeof n!="symbol"&&!!n,a.checked=c?a.checked:!!n,a.defaultChecked=!!n,i!=null&&typeof i!="function"&&typeof i!="symbol"&&typeof i!="boolean"&&(a.name=i),$e(a)}function Pe(a,l,s){l==="number"&&Et(a.ownerDocument)===a||a.defaultValue===""+s||(a.defaultValue=""+s)}function Gs(a,l,s,n){if(a=a.options,l){l={};for(var t=0;t<s.length;t++)l["$"+s[t]]=!0;for(s=0;s<a.length;s++)t=l.hasOwnProperty("$"+a[s].value),a[s].selected!==t&&(a[s].selected=t),t&&n&&(a[s].defaultSelected=!0)}else{for(s=""+Xa(s),l=null,t=0;t<a.length;t++){if(a[t].value===s){a[t].selected=!0,n&&(a[t].defaultSelected=!0);return}l!==null||a[t].disabled||(l=a[t])}l!==null&&(l.selected=!0)}}function Du(a,l,s){if(l!=null&&(l=""+Xa(l),l!==a.value&&(a.value=l),s==null)){a.defaultValue!==l&&(a.defaultValue=l);return}a.defaultValue=s!=null?""+Xa(s):""}function Bu(a,l,s,n){if(l==null){if(n!=null){if(s!=null)throw Error(f(92));if(ml(n)){if(1<n.length)throw Error(f(93));n=n[0]}s=n}s==null&&(s=""),l=s}s=Xa(l),a.defaultValue=s,n=a.textContent,n===s&&n!==""&&n!==null&&(a.value=n),$e(a)}function Ys(a,l){if(l){var s=a.firstChild;if(s&&s===a.lastChild&&s.nodeType===3){s.nodeValue=l;return}}a.textContent=l}var Qr=new Set("animationIterationCount aspectRatio borderImageOutset borderImageSlice borderImageWidth boxFlex boxFlexGroup boxOrdinalGroup columnCount columns flex flexGrow flexPositive flexShrink flexNegative flexOrder gridArea gridRow gridRowEnd gridRowSpan gridRowStart gridColumn gridColumnEnd gridColumnSpan gridColumnStart fontWeight lineClamp lineHeight opacity order orphans scale tabSize widows zIndex zoom fillOpacity floodOpacity stopOpacity strokeDasharray strokeDashoffset strokeMiterlimit strokeOpacity strokeWidth MozAnimationIterationCount MozBoxFlex MozBoxFlexGroup MozLineClamp msAnimationIterationCount msFlex msZoom msFlexGrow msFlexNegative msFlexOrder msFlexPositive msFlexShrink msGridColumn msGridColumnSpan msGridRow msGridRowSpan WebkitAnimationIterationCount WebkitBoxFlex WebKitBoxFlexGroup WebkitBoxOrdinalGroup WebkitColumnCount WebkitColumns WebkitFlex WebkitFlexGrow WebkitFlexPositive WebkitFlexShrink WebkitLineClamp".split(" "));function Uu(a,l,s){var n=l.indexOf("--")===0;s==null||typeof s=="boolean"||s===""?n?a.setProperty(l,""):l==="float"?a.cssFloat="":a[l]="":n?a.setProperty(l,s):typeof s!="number"||s===0||Qr.has(l)?l==="float"?a.cssFloat=s:a[l]=(""+s).trim():a[l]=s+"px"}function ku(a,l,s){if(l!=null&&typeof l!="object")throw Error(f(62));if(a=a.style,s!=null){for(var n in s)!s.hasOwnProperty(n)||l!=null&&l.hasOwnProperty(n)||(n.indexOf("--")===0?a.setProperty(n,""):n==="float"?a.cssFloat="":a[n]="");for(var t in l)n=l[t],l.hasOwnProperty(t)&&s[t]!==n&&Uu(a,t,n)}else for(var e in l)l.hasOwnProperty(e)&&Uu(a,e,l[e])}function ai(a){if(a.indexOf("-")===-1)return!1;switch(a){case"annotation-xml":case"color-profile":case"font-face":case"font-face-src":case"font-face-uri":case"font-face-format":case"font-face-name":case"missing-glyph":return!1;default:return!0}}var Xr=new Map([["acceptCharset","accept-charset"],["htmlFor","for"],["httpEquiv","http-equiv"],["crossOrigin","crossorigin"],["accentHeight","accent-height"],["alignmentBaseline","alignment-baseline"],["arabicForm","arabic-form"],["baselineShift","baseline-shift"],["capHeight","cap-height"],["clipPath","clip-path"],["clipRule","clip-rule"],["colorInterpolation","color-interpolation"],["colorInterpolationFilters","color-interpolation-filters"],["colorProfile","color-profile"],["colorRendering","color-rendering"],["dominantBaseline","dominant-baseline"],["enableBackground","enable-background"],["fillOpacity","fill-opacity"],["fillRule","fill-rule"],["floodColor","flood-color"],["floodOpacity","flood-opacity"],["fontFamily","font-family"],["fontSize","font-size"],["fontSizeAdjust","font-size-adjust"],["fontStretch","font-stretch"],["fontStyle","font-style"],["fontVariant","font-variant"],["fontWeight","font-weight"],["glyphName","glyph-name"],["glyphOrientationHorizontal","glyph-orientation-horizontal"],["glyphOrientationVertical","glyph-orientation-vertical"],["horizAdvX","horiz-adv-x"],["horizOriginX","horiz-origin-x"],["imageRendering","image-rendering"],["letterSpacing","letter-spacing"],["lightingColor","lighting-color"],["markerEnd","marker-end"],["markerMid","marker-mid"],["markerStart","marker-start"],["overlinePosition","overline-position"],["overlineThickness","overline-thickness"],["paintOrder","paint-order"],["panose-1","panose-1"],["pointerEvents","pointer-events"],["renderingIntent","rendering-intent"],["shapeRendering","shape-rendering"],["stopColor","stop-color"],["stopOpacity","stop-opacity"],["strikethroughPosition","strikethrough-position"],["strikethroughThickness","strikethrough-thickness"],["strokeDasharray","stroke-dasharray"],["strokeDashoffset","stroke-dashoffset"],["strokeLinecap","stroke-linecap"],["strokeLinejoin","stroke-linejoin"],["strokeMiterlimit","stroke-miterlimit"],["strokeOpacity","stroke-opacity"],["strokeWidth","stroke-width"],["textAnchor","text-anchor"],["textDecoration","text-decoration"],["textRendering","text-rendering"],["transformOrigin","transform-origin"],["underlinePosition","underline-position"],["underlineThickness","underline-thickness"],["unicodeBidi","unicode-bidi"],["unicodeRange","unicode-range"],["unitsPerEm","units-per-em"],["vAlphabetic","v-alphabetic"],["vHanging","v-hanging"],["vIdeographic","v-ideographic"],["vMathematical","v-mathematical"],["vectorEffect","vector-effect"],["vertAdvY","vert-adv-y"],["vertOriginX","vert-origin-x"],["vertOriginY","vert-origin-y"],["wordSpacing","word-spacing"],["writingMode","writing-mode"],["xmlnsXlink","xmlns:xlink"],["xHeight","x-height"]]),Vr=/^[\u0000-\u001F ]*j[\r\n\t]*a[\r\n\t]*v[\r\n\t]*a[\r\n\t]*s[\r\n\t]*c[\r\n\t]*r[\r\n\t]*i[\r\n\t]*p[\r\n\t]*t[\r\n\t]*:/i;function Ot(a){return Vr.test(""+a)?"javascript:throw new Error('React has blocked a javascript: URL as a security precaution.')":a}function bl(){}var li=null;function si(a){return a=a.target||a.srcElement||window,a.correspondingUseElement&&(a=a.correspondingUseElement),a.nodeType===3?a.parentNode:a}var Zs=null,Ls=null;function Cu(a){var l=Rs(a);if(l&&(a=l.stateNode)){var s=a[wa]||null;a:switch(a=l.stateNode,l.type){case"input":if(Ie(a,s.value,s.defaultValue,s.defaultValue,s.checked,s.defaultChecked,s.type,s.name),l=s.name,s.type==="radio"&&l!=null){for(s=a;s.parentNode;)s=s.parentNode;for(s=s.querySelectorAll('input[name="'+Va(""+l)+'"][type="radio"]'),l=0;l<s.length;l++){var n=s[l];if(n!==a&&n.form===a.form){var t=n[wa]||null;if(!t)throw Error(f(90));Ie(n,t.value,t.defaultValue,t.defaultValue,t.checked,t.defaultChecked,t.type,t.name)}}for(l=0;l<s.length;l++)n=s[l],n.form===a.form&&Eu(n)}break a;case"textarea":Du(a,s.value,s.defaultValue);break a;case"select":l=s.value,l!=null&&Gs(a,!!s.multiple,l,!1)}}}var ni=!1;function Hu(a,l,s){if(ni)return a(l,s);ni=!0;try{var n=a(l);return n}finally{if(ni=!1,(Zs!==null||Ls!==null)&&(me(),Zs&&(l=Zs,a=Ls,Ls=Zs=null,Cu(l),a)))for(l=0;l<a.length;l++)Cu(a[l])}}function En(a,l){var s=a.stateNode;if(s===null)return null;var n=s[wa]||null;if(n===null)return null;s=n[l];a:switch(l){case"onClick":case"onClickCapture":case"onDoubleClick":case"onDoubleClickCapture":case"onMouseDown":case"onMouseDownCapture":case"onMouseMove":case"onMouseMoveCapture":case"onMouseUp":case"onMouseUpCapture":case"onMouseEnter":(n=!n.disabled)||(a=a.type,n=!(a==="button"||a==="input"||a==="select"||a==="textarea")),a=!n;break a;default:a=!1}if(a)return null;if(s&&typeof s!="function")throw Error(f(231,l,typeof s));return s}var hl=!(typeof window>"u"||typeof window.document>"u"||typeof window.document.createElement>"u"),ti=!1;if(hl)try{var On={};Object.defineProperty(On,"passive",{get:function(){ti=!0}}),window.addEventListener("test",On,On),window.removeEventListener("test",On,On)}catch{ti=!1}var ql=null,ei=null,Dt=null;function _u(){if(Dt)return Dt;var a,l=ei,s=l.length,n,t="value"in ql?ql.value:ql.textContent,e=t.length;for(a=0;a<s&&l[a]===t[a];a++);var i=s-a;for(n=1;n<=i&&l[s-n]===t[e-n];n++);return Dt=t.slice(a,1<n?1-n:void 0)}function Bt(a){var l=a.keyCode;return"charCode"in a?(a=a.charCode,a===0&&l===13&&(a=13)):a=l,a===10&&(a=13),32<=a||a===13?a:0}function Ut(){return!0}function Nu(){return!1}function Ta(a){function l(s,n,t,e,i){this._reactName=s,this._targetInst=t,this.type=n,this.nativeEvent=e,this.target=i,this.currentTarget=null;for(var c in a)a.hasOwnProperty(c)&&(s=a[c],this[c]=s?s(e):e[c]);return this.isDefaultPrevented=(e.defaultPrevented!=null?e.defaultPrevented:e.returnValue===!1)?Ut:Nu,this.isPropagationStopped=Nu,this}return k(l.prototype,{preventDefault:function(){this.defaultPrevented=!0;var s=this.nativeEvent;s&&(s.preventDefault?s.preventDefault():typeof s.returnValue!="unknown"&&(s.returnValue=!1),this.isDefaultPrevented=Ut)},stopPropagation:function(){var s=this.nativeEvent;s&&(s.stopPropagation?s.stopPropagation():typeof s.cancelBubble!="unknown"&&(s.cancelBubble=!0),this.isPropagationStopped=Ut)},persist:function(){},isPersistent:Ut}),l}var fs={eventPhase:0,bubbles:0,cancelable:0,timeStamp:function(a){return a.timeStamp||Date.now()},defaultPrevented:0,isTrusted:0},kt=Ta(fs),Dn=k({},fs,{view:0,detail:0}),Kr=Ta(Dn),ii,ci,Bn,Ct=k({},Dn,{screenX:0,screenY:0,clientX:0,clientY:0,pageX:0,pageY:0,ctrlKey:0,shiftKey:0,altKey:0,metaKey:0,getModifierState:di,button:0,buttons:0,relatedTarget:function(a){return a.relatedTarget===void 0?a.fromElement===a.srcElement?a.toElement:a.fromElement:a.relatedTarget},movementX:function(a){return"movementX"in a?a.movementX:(a!==Bn&&(Bn&&a.type==="mousemove"?(ii=a.screenX-Bn.screenX,ci=a.screenY-Bn.screenY):ci=ii=0,Bn=a),ii)},movementY:function(a){return"movementY"in a?a.movementY:ci}}),Ru=Ta(Ct),Jr=k({},Ct,{dataTransfer:0}),Wr=Ta(Jr),Fr=k({},Dn,{relatedTarget:0}),ui=Ta(Fr),$r=k({},fs,{animationName:0,elapsedTime:0,pseudoElement:0}),Ir=Ta($r),Pr=k({},fs,{clipboardData:function(a){return"clipboardData"in a?a.clipboardData:window.clipboardData}}),af=Ta(Pr),lf=k({},fs,{data:0}),ju=Ta(lf),sf={Esc:"Escape",Spacebar:" ",Left:"ArrowLeft",Up:"ArrowUp",Right:"ArrowRight",Down:"ArrowDown",Del:"Delete",Win:"OS",Menu:"ContextMenu",Apps:"ContextMenu",Scroll:"ScrollLock",MozPrintableKey:"Unidentified"},nf={8:"Backspace",9:"Tab",12:"Clear",13:"Enter",16:"Shift",17:"Control",18:"Alt",19:"Pause",20:"CapsLock",27:"Escape",32:" ",33:"PageUp",34:"PageDown",35:"End",36:"Home",37:"ArrowLeft",38:"ArrowUp",39:"ArrowRight",40:"ArrowDown",45:"Insert",46:"Delete",112:"F1",113:"F2",114:"F3",115:"F4",116:"F5",117:"F6",118:"F7",119:"F8",120:"F9",121:"F10",122:"F11",123:"F12",144:"NumLock",145:"ScrollLock",224:"Meta"},tf={Alt:"altKey",Control:"ctrlKey",Meta:"metaKey",Shift:"shiftKey"};function ef(a){var l=this.nativeEvent;return l.getModifierState?l.getModifierState(a):(a=tf[a])?!!l[a]:!1}function di(){return ef}var cf=k({},Dn,{key:function(a){if(a.key){var l=sf[a.key]||a.key;if(l!=="Unidentified")return l}return a.type==="keypress"?(a=Bt(a),a===13?"Enter":String.fromCharCode(a)):a.type==="keydown"||a.type==="keyup"?nf[a.keyCode]||"Unidentified":""},code:0,location:0,ctrlKey:0,shiftKey:0,altKey:0,metaKey:0,repeat:0,locale:0,getModifierState:di,charCode:function(a){return a.type==="keypress"?Bt(a):0},keyCode:function(a){return a.type==="keydown"||a.type==="keyup"?a.keyCode:0},which:function(a){return a.type==="keypress"?Bt(a):a.type==="keydown"||a.type==="keyup"?a.keyCode:0}}),uf=Ta(cf),df=k({},Ct,{pointerId:0,width:0,height:0,pressure:0,tangentialPressure:0,tiltX:0,tiltY:0,twist:0,pointerType:0,isPrimary:0}),qu=Ta(df),of=k({},Dn,{touches:0,targetTouches:0,changedTouches:0,altKey:0,metaKey:0,ctrlKey:0,shiftKey:0,getModifierState:di}),vf=Ta(of),rf=k({},fs,{propertyName:0,elapsedTime:0,pseudoElement:0}),ff=Ta(rf),pf=k({},Ct,{deltaX:function(a){return"deltaX"in a?a.deltaX:"wheelDeltaX"in a?-a.wheelDeltaX:0},deltaY:function(a){return"deltaY"in a?a.deltaY:"wheelDeltaY"in a?-a.wheelDeltaY:"wheelDelta"in a?-a.wheelDelta:0},deltaZ:0,deltaMode:0}),mf=Ta(pf),gf=k({},fs,{newState:0,oldState:0}),bf=Ta(gf),hf=[9,13,27,32],oi=hl&&"CompositionEvent"in window,Un=null;hl&&"documentMode"in document&&(Un=document.documentMode);var yf=hl&&"TextEvent"in window&&!Un,Gu=hl&&(!oi||Un&&8<Un&&11>=Un),Yu=" ",Zu=!1;function Lu(a,l){switch(a){case"keyup":return hf.indexOf(l.keyCode)!==-1;case"keydown":return l.keyCode!==229;case"keypress":case"mousedown":case"focusout":return!0;default:return!1}}function Qu(a){return a=a.detail,typeof a=="object"&&"data"in a?a.data:null}var Qs=!1;function Sf(a,l){switch(a){case"compositionend":return Qu(l);case"keypress":return l.which!==32?null:(Zu=!0,Yu);case"textInput":return a=l.data,a===Yu&&Zu?null:a;default:return null}}function xf(a,l){if(Qs)return a==="compositionend"||!oi&&Lu(a,l)?(a=_u(),Dt=ei=ql=null,Qs=!1,a):null;switch(a){case"paste":return null;case"keypress":if(!(l.ctrlKey||l.altKey||l.metaKey)||l.ctrlKey&&l.altKey){if(l.char&&1<l.char.length)return l.char;if(l.which)return String.fromCharCode(l.which)}return null;case"compositionend":return Gu&&l.locale!=="ko"?null:l.data;default:return null}}var zf={color:!0,date:!0,datetime:!0,"datetime-local":!0,email:!0,month:!0,number:!0,password:!0,range:!0,search:!0,tel:!0,text:!0,time:!0,url:!0,week:!0};function Xu(a){var l=a&&a.nodeName&&a.nodeName.toLowerCase();return l==="input"?!!zf[a.type]:l==="textarea"}function Vu(a,l,s,n){Zs?Ls?Ls.push(n):Ls=[n]:Zs=n,l=ze(l,"onChange"),0<l.length&&(s=new kt("onChange","change",null,s,n),a.push({event:s,listeners:l}))}var kn=null,Cn=null;function Af(a){Dv(a,0)}function Ht(a){var l=Mn(a);if(Eu(l))return a}function Ku(a,l){if(a==="change")return l}var Ju=!1;if(hl){var vi;if(hl){var ri="oninput"in document;if(!ri){var Wu=document.createElement("div");Wu.setAttribute("oninput","return;"),ri=typeof Wu.oninput=="function"}vi=ri}else vi=!1;Ju=vi&&(!document.documentMode||9<document.documentMode)}function Fu(){kn&&(kn.detachEvent("onpropertychange",$u),Cn=kn=null)}function $u(a){if(a.propertyName==="value"&&Ht(Cn)){var l=[];Vu(l,Cn,a,si(a)),Hu(Af,l)}}function wf(a,l,s){a==="focusin"?(Fu(),kn=l,Cn=s,kn.attachEvent("onpropertychange",$u)):a==="focusout"&&Fu()}function Tf(a){if(a==="selectionchange"||a==="keyup"||a==="keydown")return Ht(Cn)}function Mf(a,l){if(a==="click")return Ht(l)}function Ef(a,l){if(a==="input"||a==="change")return Ht(l)}function Of(a,l){return a===l&&(a!==0||1/a===1/l)||a!==a&&l!==l}var Ha=typeof Object.is=="function"?Object.is:Of;function Hn(a,l){if(Ha(a,l))return!0;if(typeof a!="object"||a===null||typeof l!="object"||l===null)return!1;var s=Object.keys(a),n=Object.keys(l);if(s.length!==n.length)return!1;for(n=0;n<s.length;n++){var t=s[n];if(!Le.call(l,t)||!Ha(a[t],l[t]))return!1}return!0}function Iu(a){for(;a&&a.firstChild;)a=a.firstChild;return a}function Pu(a,l){var s=Iu(a);a=0;for(var n;s;){if(s.nodeType===3){if(n=a+s.textContent.length,a<=l&&n>=l)return{node:s,offset:l-a};a=n}a:{for(;s;){if(s.nextSibling){s=s.nextSibling;break a}s=s.parentNode}s=void 0}s=Iu(s)}}function ad(a,l){return a&&l?a===l?!0:a&&a.nodeType===3?!1:l&&l.nodeType===3?ad(a,l.parentNode):"contains"in a?a.contains(l):a.compareDocumentPosition?!!(a.compareDocumentPosition(l)&16):!1:!1}function ld(a){a=a!=null&&a.ownerDocument!=null&&a.ownerDocument.defaultView!=null?a.ownerDocument.defaultView:window;for(var l=Et(a.document);l instanceof a.HTMLIFrameElement;){try{var s=typeof l.contentWindow.location.href=="string"}catch{s=!1}if(s)a=l.contentWindow;else break;l=Et(a.document)}return l}function fi(a){var l=a&&a.nodeName&&a.nodeName.toLowerCase();return l&&(l==="input"&&(a.type==="text"||a.type==="search"||a.type==="tel"||a.type==="url"||a.type==="password")||l==="textarea"||a.contentEditable==="true")}var Df=hl&&"documentMode"in document&&11>=document.documentMode,Xs=null,pi=null,_n=null,mi=!1;function sd(a,l,s){var n=s.window===s?s.document:s.nodeType===9?s:s.ownerDocument;mi||Xs==null||Xs!==Et(n)||(n=Xs,"selectionStart"in n&&fi(n)?n={start:n.selectionStart,end:n.selectionEnd}:(n=(n.ownerDocument&&n.ownerDocument.defaultView||window).getSelection(),n={anchorNode:n.anchorNode,anchorOffset:n.anchorOffset,focusNode:n.focusNode,focusOffset:n.focusOffset}),_n&&Hn(_n,n)||(_n=n,n=ze(pi,"onSelect"),0<n.length&&(l=new kt("onSelect","select",null,l,s),a.push({event:l,listeners:n}),l.target=Xs)))}function ps(a,l){var s={};return s[a.toLowerCase()]=l.toLowerCase(),s["Webkit"+a]="webkit"+l,s["Moz"+a]="moz"+l,s}var Vs={animationend:ps("Animation","AnimationEnd"),animationiteration:ps("Animation","AnimationIteration"),animationstart:ps("Animation","AnimationStart"),transitionrun:ps("Transition","TransitionRun"),transitionstart:ps("Transition","TransitionStart"),transitioncancel:ps("Transition","TransitionCancel"),transitionend:ps("Transition","TransitionEnd")},gi={},nd={};hl&&(nd=document.createElement("div").style,"AnimationEvent"in window||(delete Vs.animationend.animation,delete Vs.animationiteration.animation,delete Vs.animationstart.animation),"TransitionEvent"in window||delete Vs.transitionend.transition);function ms(a){if(gi[a])return gi[a];if(!Vs[a])return a;var l=Vs[a],s;for(s in l)if(l.hasOwnProperty(s)&&s in nd)return gi[a]=l[s];return a}var td=ms("animationend"),ed=ms("animationiteration"),id=ms("animationstart"),Bf=ms("transitionrun"),Uf=ms("transitionstart"),kf=ms("transitioncancel"),cd=ms("transitionend"),ud=new Map,bi="abort auxClick beforeToggle cancel canPlay canPlayThrough click close contextMenu copy cut drag dragEnd dragEnter dragExit dragLeave dragOver dragStart drop durationChange emptied encrypted ended error gotPointerCapture input invalid keyDown keyPress keyUp load loadedData loadedMetadata loadStart lostPointerCapture mouseDown mouseMove mouseOut mouseOver mouseUp paste pause play playing pointerCancel pointerDown pointerMove pointerOut pointerOver pointerUp progress rateChange reset resize seeked seeking stalled submit suspend timeUpdate touchCancel touchEnd touchStart volumeChange scroll toggle touchMove waiting wheel".split(" ");bi.push("scrollEnd");function nl(a,l){ud.set(a,l),rs(l,[a])}var _t=typeof reportError=="function"?reportError:function(a){if(typeof window=="object"&&typeof window.ErrorEvent=="function"){var l=new window.ErrorEvent("error",{bubbles:!0,cancelable:!0,message:typeof a=="object"&&a!==null&&typeof a.message=="string"?String(a.message):String(a),error:a});if(!window.dispatchEvent(l))return}else if(typeof process=="object"&&typeof process.emit=="function"){process.emit("uncaughtException",a);return}console.error(a)},Ka=[],Ks=0,hi=0;function Nt(){for(var a=Ks,l=hi=Ks=0;l<a;){var s=Ka[l];Ka[l++]=null;var n=Ka[l];Ka[l++]=null;var t=Ka[l];Ka[l++]=null;var e=Ka[l];if(Ka[l++]=null,n!==null&&t!==null){var i=n.pending;i===null?t.next=t:(t.next=i.next,i.next=t),n.pending=t}e!==0&&dd(s,t,e)}}function Rt(a,l,s,n){Ka[Ks++]=a,Ka[Ks++]=l,Ka[Ks++]=s,Ka[Ks++]=n,hi|=n,a.lanes|=n,a=a.alternate,a!==null&&(a.lanes|=n)}function yi(a,l,s,n){return Rt(a,l,s,n),jt(a)}function gs(a,l){return Rt(a,null,null,l),jt(a)}function dd(a,l,s){a.lanes|=s;var n=a.alternate;n!==null&&(n.lanes|=s);for(var t=!1,e=a.return;e!==null;)e.childLanes|=s,n=e.alternate,n!==null&&(n.childLanes|=s),e.tag===22&&(a=e.stateNode,a===null||a._visibility&1||(t=!0)),a=e,e=e.return;return a.tag===3?(e=a.stateNode,t&&l!==null&&(t=31-Ca(s),a=e.hiddenUpdates,n=a[t],n===null?a[t]=[l]:n.push(l),l.lane=s|536870912),e):null}function jt(a){if(50<nt)throw nt=0,Oc=null,Error(f(185));for(var l=a.return;l!==null;)a=l,l=a.return;return a.tag===3?a.stateNode:null}var Js={};function Cf(a,l,s,n){this.tag=a,this.key=s,this.sibling=this.child=this.return=this.stateNode=this.type=this.elementType=null,this.index=0,this.refCleanup=this.ref=null,this.pendingProps=l,this.dependencies=this.memoizedState=this.updateQueue=this.memoizedProps=null,this.mode=n,this.subtreeFlags=this.flags=0,this.deletions=null,this.childLanes=this.lanes=0,this.alternate=null}function _a(a,l,s,n){return new Cf(a,l,s,n)}function Si(a){return a=a.prototype,!(!a||!a.isReactComponent)}function yl(a,l){var s=a.alternate;return s===null?(s=_a(a.tag,l,a.key,a.mode),s.elementType=a.elementType,s.type=a.type,s.stateNode=a.stateNode,s.alternate=a,a.alternate=s):(s.pendingProps=l,s.type=a.type,s.flags=0,s.subtreeFlags=0,s.deletions=null),s.flags=a.flags&65011712,s.childLanes=a.childLanes,s.lanes=a.lanes,s.child=a.child,s.memoizedProps=a.memoizedProps,s.memoizedState=a.memoizedState,s.updateQueue=a.updateQueue,l=a.dependencies,s.dependencies=l===null?null:{lanes:l.lanes,firstContext:l.firstContext},s.sibling=a.sibling,s.index=a.index,s.ref=a.ref,s.refCleanup=a.refCleanup,s}function od(a,l){a.flags&=65011714;var s=a.alternate;return s===null?(a.childLanes=0,a.lanes=l,a.child=null,a.subtreeFlags=0,a.memoizedProps=null,a.memoizedState=null,a.updateQueue=null,a.dependencies=null,a.stateNode=null):(a.childLanes=s.childLanes,a.lanes=s.lanes,a.child=s.child,a.subtreeFlags=0,a.deletions=null,a.memoizedProps=s.memoizedProps,a.memoizedState=s.memoizedState,a.updateQueue=s.updateQueue,a.type=s.type,l=s.dependencies,a.dependencies=l===null?null:{lanes:l.lanes,firstContext:l.firstContext}),a}function qt(a,l,s,n,t,e){var i=0;if(n=a,typeof a=="function")Si(a)&&(i=1);else if(typeof a=="string")i=jp(a,s,ra.current)?26:a==="html"||a==="head"||a==="body"?27:5;else a:switch(a){case ks:return a=_a(31,s,l,t),a.elementType=ks,a.lanes=e,a;case Za:return bs(s.children,t,e,l);case Bs:i=8,t|=24;break;case Us:return a=_a(12,s,l,t|2),a.elementType=Us,a.lanes=e,a;case ds:return a=_a(13,s,l,t),a.elementType=ds,a.lanes=e,a;case cl:return a=_a(19,s,l,t),a.elementType=cl,a.lanes=e,a;default:if(typeof a=="object"&&a!==null)switch(a.$$typeof){case La:i=10;break a;case Sn:i=9;break a;case _l:i=11;break a;case pl:i=14;break a;case sl:i=16,n=null;break a}i=29,s=Error(f(130,a===null?"null":typeof a,"")),n=null}return l=_a(i,s,l,t),l.elementType=a,l.type=n,l.lanes=e,l}function bs(a,l,s,n){return a=_a(7,a,n,l),a.lanes=s,a}function xi(a,l,s){return a=_a(6,a,null,l),a.lanes=s,a}function vd(a){var l=_a(18,null,null,0);return l.stateNode=a,l}function zi(a,l,s){return l=_a(4,a.children!==null?a.children:[],a.key,l),l.lanes=s,l.stateNode={containerInfo:a.containerInfo,pendingChildren:null,implementation:a.implementation},l}var rd=new WeakMap;function Ja(a,l){if(typeof a=="object"&&a!==null){var s=rd.get(a);return s!==void 0?s:(l={value:a,source:l,stack:vu(l)},rd.set(a,l),l)}return{value:a,source:l,stack:vu(l)}}var Ws=[],Fs=0,Gt=null,Nn=0,Wa=[],Fa=0,Gl=null,dl=1,ol="";function Sl(a,l){Ws[Fs++]=Nn,Ws[Fs++]=Gt,Gt=a,Nn=l}function fd(a,l,s){Wa[Fa++]=dl,Wa[Fa++]=ol,Wa[Fa++]=Gl,Gl=a;var n=dl;a=ol;var t=32-Ca(n)-1;n&=~(1<<t),s+=1;var e=32-Ca(l)+t;if(30<e){var i=t-t%5;e=(n&(1<<i)-1).toString(32),n>>=i,t-=i,dl=1<<32-Ca(l)+t|s<<t|n,ol=e+a}else dl=1<<e|s<<t|n,ol=a}function Ai(a){a.return!==null&&(Sl(a,1),fd(a,1,0))}function wi(a){for(;a===Gt;)Gt=Ws[--Fs],Ws[Fs]=null,Nn=Ws[--Fs],Ws[Fs]=null;for(;a===Gl;)Gl=Wa[--Fa],Wa[Fa]=null,ol=Wa[--Fa],Wa[Fa]=null,dl=Wa[--Fa],Wa[Fa]=null}function pd(a,l){Wa[Fa++]=dl,Wa[Fa++]=ol,Wa[Fa++]=Gl,dl=l.id,ol=l.overflow,Gl=a}var ga=null,I=null,q=!1,Yl=null,$a=!1,Ti=Error(f(519));function Zl(a){var l=Error(f(418,1<arguments.length&&arguments[1]!==void 0&&arguments[1]?"text":"HTML",""));throw Rn(Ja(l,a)),Ti}function md(a){var l=a.stateNode,s=a.type,n=a.memoizedProps;switch(l[ma]=a,l[wa]=n,s){case"dialog":_("cancel",l),_("close",l);break;case"iframe":case"object":case"embed":_("load",l);break;case"video":case"audio":for(s=0;s<et.length;s++)_(et[s],l);break;case"source":_("error",l);break;case"img":case"image":case"link":_("error",l),_("load",l);break;case"details":_("toggle",l);break;case"input":_("invalid",l),Ou(l,n.value,n.defaultValue,n.checked,n.defaultChecked,n.type,n.name,!0);break;case"select":_("invalid",l);break;case"textarea":_("invalid",l),Bu(l,n.value,n.defaultValue,n.children)}s=n.children,typeof s!="string"&&typeof s!="number"&&typeof s!="bigint"||l.textContent===""+s||n.suppressHydrationWarning===!0||Cv(l.textContent,s)?(n.popover!=null&&(_("beforetoggle",l),_("toggle",l)),n.onScroll!=null&&_("scroll",l),n.onScrollEnd!=null&&_("scrollend",l),n.onClick!=null&&(l.onclick=bl),l=!0):l=!1,l||Zl(a,!0)}function gd(a){for(ga=a.return;ga;)switch(ga.tag){case 5:case 31:case 13:$a=!1;return;case 27:case 3:$a=!0;return;default:ga=ga.return}}function $s(a){if(a!==ga)return!1;if(!q)return gd(a),q=!0,!1;var l=a.tag,s;if((s=l!==3&&l!==27)&&((s=l===5)&&(s=a.type,s=!(s!=="form"&&s!=="button")||Lc(a.type,a.memoizedProps)),s=!s),s&&I&&Zl(a),gd(a),l===13){if(a=a.memoizedState,a=a!==null?a.dehydrated:null,!a)throw Error(f(317));I=Zv(a)}else if(l===31){if(a=a.memoizedState,a=a!==null?a.dehydrated:null,!a)throw Error(f(317));I=Zv(a)}else l===27?(l=I,ss(a.type)?(a=Jc,Jc=null,I=a):I=l):I=ga?Pa(a.stateNode.nextSibling):null;return!0}function hs(){I=ga=null,q=!1}function Mi(){var a=Yl;return a!==null&&(Da===null?Da=a:Da.push.apply(Da,a),Yl=null),a}function Rn(a){Yl===null?Yl=[a]:Yl.push(a)}var Ei=xa(null),ys=null,xl=null;function Ll(a,l,s){L(Ei,l._currentValue),l._currentValue=s}function zl(a){a._currentValue=Ei.current,la(Ei)}function Oi(a,l,s){for(;a!==null;){var n=a.alternate;if((a.childLanes&l)!==l?(a.childLanes|=l,n!==null&&(n.childLanes|=l)):n!==null&&(n.childLanes&l)!==l&&(n.childLanes|=l),a===s)break;a=a.return}}function Di(a,l,s,n){var t=a.child;for(t!==null&&(t.return=a);t!==null;){var e=t.dependencies;if(e!==null){var i=t.child;e=e.firstContext;a:for(;e!==null;){var c=e;e=t;for(var u=0;u<l.length;u++)if(c.context===l[u]){e.lanes|=s,c=e.alternate,c!==null&&(c.lanes|=s),Oi(e.return,s,a),n||(i=null);break a}e=c.next}}else if(t.tag===18){if(i=t.return,i===null)throw Error(f(341));i.lanes|=s,e=i.alternate,e!==null&&(e.lanes|=s),Oi(i,s,a),i=null}else i=t.child;if(i!==null)i.return=t;else for(i=t;i!==null;){if(i===a){i=null;break}if(t=i.sibling,t!==null){t.return=i.return,i=t;break}i=i.return}t=i}}function Is(a,l,s,n){a=null;for(var t=l,e=!1;t!==null;){if(!e){if((t.flags&524288)!==0)e=!0;else if((t.flags&262144)!==0)break}if(t.tag===10){var i=t.alternate;if(i===null)throw Error(f(387));if(i=i.memoizedProps,i!==null){var c=t.type;Ha(t.pendingProps.value,i.value)||(a!==null?a.push(c):a=[c])}}else if(t===bt.current){if(i=t.alternate,i===null)throw Error(f(387));i.memoizedState.memoizedState!==t.memoizedState.memoizedState&&(a!==null?a.push(ot):a=[ot])}t=t.return}a!==null&&Di(l,a,s,n),l.flags|=262144}function Yt(a){for(a=a.firstContext;a!==null;){if(!Ha(a.context._currentValue,a.memoizedValue))return!0;a=a.next}return!1}function Ss(a){ys=a,xl=null,a=a.dependencies,a!==null&&(a.firstContext=null)}function ba(a){return bd(ys,a)}function Zt(a,l){return ys===null&&Ss(a),bd(a,l)}function bd(a,l){var s=l._currentValue;if(l={context:l,memoizedValue:s,next:null},xl===null){if(a===null)throw Error(f(308));xl=l,a.dependencies={lanes:0,firstContext:l},a.flags|=524288}else xl=xl.next=l;return s}var Hf=typeof AbortController<"u"?AbortController:function(){var a=[],l=this.signal={aborted:!1,addEventListener:function(s,n){a.push(n)}};this.abort=function(){l.aborted=!0,a.forEach(function(s){return s()})}},_f=S.unstable_scheduleCallback,Nf=S.unstable_NormalPriority,ia={$$typeof:La,Consumer:null,Provider:null,_currentValue:null,_currentValue2:null,_threadCount:0};function Bi(){return{controller:new Hf,data:new Map,refCount:0}}function jn(a){a.refCount--,a.refCount===0&&_f(Nf,function(){a.controller.abort()})}var qn=null,Ui=0,Ps=0,an=null;function Rf(a,l){if(qn===null){var s=qn=[];Ui=0,Ps=Hc(),an={status:"pending",value:void 0,then:function(n){s.push(n)}}}return Ui++,l.then(hd,hd),l}function hd(){if(--Ui===0&&qn!==null){an!==null&&(an.status="fulfilled");var a=qn;qn=null,Ps=0,an=null;for(var l=0;l<a.length;l++)(0,a[l])()}}function jf(a,l){var s=[],n={status:"pending",value:null,reason:null,then:function(t){s.push(t)}};return a.then(function(){n.status="fulfilled",n.value=l;for(var t=0;t<s.length;t++)(0,s[t])(l)},function(t){for(n.status="rejected",n.reason=t,t=0;t<s.length;t++)(0,s[t])(void 0)}),n}var yd=h.S;h.S=function(a,l){nv=Ua(),typeof l=="object"&&l!==null&&typeof l.then=="function"&&Rf(a,l),yd!==null&&yd(a,l)};var xs=xa(null);function ki(){var a=xs.current;return a!==null?a:W.pooledCache}function Lt(a,l){l===null?L(xs,xs.current):L(xs,l.pool)}function Sd(){var a=ki();return a===null?null:{parent:ia._currentValue,pool:a}}var ln=Error(f(460)),Ci=Error(f(474)),Qt=Error(f(542)),Xt={then:function(){}};function xd(a){return a=a.status,a==="fulfilled"||a==="rejected"}function zd(a,l,s){switch(s=a[s],s===void 0?a.push(l):s!==l&&(l.then(bl,bl),l=s),l.status){case"fulfilled":return l.value;case"rejected":throw a=l.reason,wd(a),a;default:if(typeof l.status=="string")l.then(bl,bl);else{if(a=W,a!==null&&100<a.shellSuspendCounter)throw Error(f(482));a=l,a.status="pending",a.then(function(n){if(l.status==="pending"){var t=l;t.status="fulfilled",t.value=n}},function(n){if(l.status==="pending"){var t=l;t.status="rejected",t.reason=n}})}switch(l.status){case"fulfilled":return l.value;case"rejected":throw a=l.reason,wd(a),a}throw As=l,ln}}function zs(a){try{var l=a._init;return l(a._payload)}catch(s){throw s!==null&&typeof s=="object"&&typeof s.then=="function"?(As=s,ln):s}}var As=null;function Ad(){if(As===null)throw Error(f(459));var a=As;return As=null,a}function wd(a){if(a===ln||a===Qt)throw Error(f(483))}var sn=null,Gn=0;function Vt(a){var l=Gn;return Gn+=1,sn===null&&(sn=[]),zd(sn,a,l)}function Yn(a,l){l=l.props.ref,a.ref=l!==void 0?l:null}function Kt(a,l){throw l.$$typeof===va?Error(f(525)):(a=Object.prototype.toString.call(l),Error(f(31,a==="[object Object]"?"object with keys {"+Object.keys(l).join(", ")+"}":a)))}function Td(a){function l(o,d){if(a){var v=o.deletions;v===null?(o.deletions=[d],o.flags|=16):v.push(d)}}function s(o,d){if(!a)return null;for(;d!==null;)l(o,d),d=d.sibling;return null}function n(o){for(var d=new Map;o!==null;)o.key!==null?d.set(o.key,o):d.set(o.index,o),o=o.sibling;return d}function t(o,d){return o=yl(o,d),o.index=0,o.sibling=null,o}function e(o,d,v){return o.index=v,a?(v=o.alternate,v!==null?(v=v.index,v<d?(o.flags|=67108866,d):v):(o.flags|=67108866,d)):(o.flags|=1048576,d)}function i(o){return a&&o.alternate===null&&(o.flags|=67108866),o}function c(o,d,v,b){return d===null||d.tag!==6?(d=xi(v,o.mode,b),d.return=o,d):(d=t(d,v),d.return=o,d)}function u(o,d,v,b){var w=v.type;return w===Za?g(o,d,v.props.children,b,v.key):d!==null&&(d.elementType===w||typeof w=="object"&&w!==null&&w.$$typeof===sl&&zs(w)===d.type)?(d=t(d,v.props),Yn(d,v),d.return=o,d):(d=qt(v.type,v.key,v.props,null,o.mode,b),Yn(d,v),d.return=o,d)}function r(o,d,v,b){return d===null||d.tag!==4||d.stateNode.containerInfo!==v.containerInfo||d.stateNode.implementation!==v.implementation?(d=zi(v,o.mode,b),d.return=o,d):(d=t(d,v.children||[]),d.return=o,d)}function g(o,d,v,b,w){return d===null||d.tag!==7?(d=bs(v,o.mode,b,w),d.return=o,d):(d=t(d,v),d.return=o,d)}function y(o,d,v){if(typeof d=="string"&&d!==""||typeof d=="number"||typeof d=="bigint")return d=xi(""+d,o.mode,v),d.return=o,d;if(typeof d=="object"&&d!==null){switch(d.$$typeof){case Hl:return v=qt(d.type,d.key,d.props,null,o.mode,v),Yn(v,d),v.return=o,v;case ll:return d=zi(d,o.mode,v),d.return=o,d;case sl:return d=zs(d),y(o,d,v)}if(ml(d)||Qa(d))return d=bs(d,o.mode,v,null),d.return=o,d;if(typeof d.then=="function")return y(o,Vt(d),v);if(d.$$typeof===La)return y(o,Zt(o,d),v);Kt(o,d)}return null}function p(o,d,v,b){var w=d!==null?d.key:null;if(typeof v=="string"&&v!==""||typeof v=="number"||typeof v=="bigint")return w!==null?null:c(o,d,""+v,b);if(typeof v=="object"&&v!==null){switch(v.$$typeof){case Hl:return v.key===w?u(o,d,v,b):null;case ll:return v.key===w?r(o,d,v,b):null;case sl:return v=zs(v),p(o,d,v,b)}if(ml(v)||Qa(v))return w!==null?null:g(o,d,v,b,null);if(typeof v.then=="function")return p(o,d,Vt(v),b);if(v.$$typeof===La)return p(o,d,Zt(o,v),b);Kt(o,v)}return null}function m(o,d,v,b,w){if(typeof b=="string"&&b!==""||typeof b=="number"||typeof b=="bigint")return o=o.get(v)||null,c(d,o,""+b,w);if(typeof b=="object"&&b!==null){switch(b.$$typeof){case Hl:return o=o.get(b.key===null?v:b.key)||null,u(d,o,b,w);case ll:return o=o.get(b.key===null?v:b.key)||null,r(d,o,b,w);case sl:return b=zs(b),m(o,d,v,b,w)}if(ml(b)||Qa(b))return o=o.get(v)||null,g(d,o,b,w,null);if(typeof b.then=="function")return m(o,d,v,Vt(b),w);if(b.$$typeof===La)return m(o,d,v,Zt(d,b),w);Kt(d,b)}return null}function z(o,d,v,b){for(var w=null,G=null,A=d,B=d=0,j=null;A!==null&&B<v.length;B++){A.index>B?(j=A,A=null):j=A.sibling;var Y=p(o,A,v[B],b);if(Y===null){A===null&&(A=j);break}a&&A&&Y.alternate===null&&l(o,A),d=e(Y,d,B),G===null?w=Y:G.sibling=Y,G=Y,A=j}if(B===v.length)return s(o,A),q&&Sl(o,B),w;if(A===null){for(;B<v.length;B++)A=y(o,v[B],b),A!==null&&(d=e(A,d,B),G===null?w=A:G.sibling=A,G=A);return q&&Sl(o,B),w}for(A=n(A);B<v.length;B++)j=m(A,o,B,v[B],b),j!==null&&(a&&j.alternate!==null&&A.delete(j.key===null?B:j.key),d=e(j,d,B),G===null?w=j:G.sibling=j,G=j);return a&&A.forEach(function(cs){return l(o,cs)}),q&&Sl(o,B),w}function T(o,d,v,b){if(v==null)throw Error(f(151));for(var w=null,G=null,A=d,B=d=0,j=null,Y=v.next();A!==null&&!Y.done;B++,Y=v.next()){A.index>B?(j=A,A=null):j=A.sibling;var cs=p(o,A,Y.value,b);if(cs===null){A===null&&(A=j);break}a&&A&&cs.alternate===null&&l(o,A),d=e(cs,d,B),G===null?w=cs:G.sibling=cs,G=cs,A=j}if(Y.done)return s(o,A),q&&Sl(o,B),w;if(A===null){for(;!Y.done;B++,Y=v.next())Y=y(o,Y.value,b),Y!==null&&(d=e(Y,d,B),G===null?w=Y:G.sibling=Y,G=Y);return q&&Sl(o,B),w}for(A=n(A);!Y.done;B++,Y=v.next())Y=m(A,o,B,Y.value,b),Y!==null&&(a&&Y.alternate!==null&&A.delete(Y.key===null?B:Y.key),d=e(Y,d,B),G===null?w=Y:G.sibling=Y,G=Y);return a&&A.forEach(function(Wp){return l(o,Wp)}),q&&Sl(o,B),w}function J(o,d,v,b){if(typeof v=="object"&&v!==null&&v.type===Za&&v.key===null&&(v=v.props.children),typeof v=="object"&&v!==null){switch(v.$$typeof){case Hl:a:{for(var w=v.key;d!==null;){if(d.key===w){if(w=v.type,w===Za){if(d.tag===7){s(o,d.sibling),b=t(d,v.props.children),b.return=o,o=b;break a}}else if(d.elementType===w||typeof w=="object"&&w!==null&&w.$$typeof===sl&&zs(w)===d.type){s(o,d.sibling),b=t(d,v.props),Yn(b,v),b.return=o,o=b;break a}s(o,d);break}else l(o,d);d=d.sibling}v.type===Za?(b=bs(v.props.children,o.mode,b,v.key),b.return=o,o=b):(b=qt(v.type,v.key,v.props,null,o.mode,b),Yn(b,v),b.return=o,o=b)}return i(o);case ll:a:{for(w=v.key;d!==null;){if(d.key===w)if(d.tag===4&&d.stateNode.containerInfo===v.containerInfo&&d.stateNode.implementation===v.implementation){s(o,d.sibling),b=t(d,v.children||[]),b.return=o,o=b;break a}else{s(o,d);break}else l(o,d);d=d.sibling}b=zi(v,o.mode,b),b.return=o,o=b}return i(o);case sl:return v=zs(v),J(o,d,v,b)}if(ml(v))return z(o,d,v,b);if(Qa(v)){if(w=Qa(v),typeof w!="function")throw Error(f(150));return v=w.call(v),T(o,d,v,b)}if(typeof v.then=="function")return J(o,d,Vt(v),b);if(v.$$typeof===La)return J(o,d,Zt(o,v),b);Kt(o,v)}return typeof v=="string"&&v!==""||typeof v=="number"||typeof v=="bigint"?(v=""+v,d!==null&&d.tag===6?(s(o,d.sibling),b=t(d,v),b.return=o,o=b):(s(o,d),b=xi(v,o.mode,b),b.return=o,o=b),i(o)):s(o,d)}return function(o,d,v,b){try{Gn=0;var w=J(o,d,v,b);return sn=null,w}catch(A){if(A===ln||A===Qt)throw A;var G=_a(29,A,null,o.mode);return G.lanes=b,G.return=o,G}finally{}}}var ws=Td(!0),Md=Td(!1),Ql=!1;function Hi(a){a.updateQueue={baseState:a.memoizedState,firstBaseUpdate:null,lastBaseUpdate:null,shared:{pending:null,lanes:0,hiddenCallbacks:null},callbacks:null}}function _i(a,l){a=a.updateQueue,l.updateQueue===a&&(l.updateQueue={baseState:a.baseState,firstBaseUpdate:a.firstBaseUpdate,lastBaseUpdate:a.lastBaseUpdate,shared:a.shared,callbacks:null})}function Xl(a){return{lane:a,tag:0,payload:null,callback:null,next:null}}function Vl(a,l,s){var n=a.updateQueue;if(n===null)return null;if(n=n.shared,(Z&2)!==0){var t=n.pending;return t===null?l.next=l:(l.next=t.next,t.next=l),n.pending=l,l=jt(a),dd(a,null,s),l}return Rt(a,n,l,s),jt(a)}function Zn(a,l,s){if(l=l.updateQueue,l!==null&&(l=l.shared,(s&4194048)!==0)){var n=l.lanes;n&=a.pendingLanes,s|=n,l.lanes=s,bu(a,s)}}function Ni(a,l){var s=a.updateQueue,n=a.alternate;if(n!==null&&(n=n.updateQueue,s===n)){var t=null,e=null;if(s=s.firstBaseUpdate,s!==null){do{var i={lane:s.lane,tag:s.tag,payload:s.payload,callback:null,next:null};e===null?t=e=i:e=e.next=i,s=s.next}while(s!==null);e===null?t=e=l:e=e.next=l}else t=e=l;s={baseState:n.baseState,firstBaseUpdate:t,lastBaseUpdate:e,shared:n.shared,callbacks:n.callbacks},a.updateQueue=s;return}a=s.lastBaseUpdate,a===null?s.firstBaseUpdate=l:a.next=l,s.lastBaseUpdate=l}var Ri=!1;function Ln(){if(Ri){var a=an;if(a!==null)throw a}}function Qn(a,l,s,n){Ri=!1;var t=a.updateQueue;Ql=!1;var e=t.firstBaseUpdate,i=t.lastBaseUpdate,c=t.shared.pending;if(c!==null){t.shared.pending=null;var u=c,r=u.next;u.next=null,i===null?e=r:i.next=r,i=u;var g=a.alternate;g!==null&&(g=g.updateQueue,c=g.lastBaseUpdate,c!==i&&(c===null?g.firstBaseUpdate=r:c.next=r,g.lastBaseUpdate=u))}if(e!==null){var y=t.baseState;i=0,g=r=u=null,c=e;do{var p=c.lane&-536870913,m=p!==c.lane;if(m?(R&p)===p:(n&p)===p){p!==0&&p===Ps&&(Ri=!0),g!==null&&(g=g.next={lane:0,tag:c.tag,payload:c.payload,callback:null,next:null});a:{var z=a,T=c;p=l;var J=s;switch(T.tag){case 1:if(z=T.payload,typeof z=="function"){y=z.call(J,y,p);break a}y=z;break a;case 3:z.flags=z.flags&-65537|128;case 0:if(z=T.payload,p=typeof z=="function"?z.call(J,y,p):z,p==null)break a;y=k({},y,p);break a;case 2:Ql=!0}}p=c.callback,p!==null&&(a.flags|=64,m&&(a.flags|=8192),m=t.callbacks,m===null?t.callbacks=[p]:m.push(p))}else m={lane:p,tag:c.tag,payload:c.payload,callback:c.callback,next:null},g===null?(r=g=m,u=y):g=g.next=m,i|=p;if(c=c.next,c===null){if(c=t.shared.pending,c===null)break;m=c,c=m.next,m.next=null,t.lastBaseUpdate=m,t.shared.pending=null}}while(!0);g===null&&(u=y),t.baseState=u,t.firstBaseUpdate=r,t.lastBaseUpdate=g,e===null&&(t.shared.lanes=0),$l|=i,a.lanes=i,a.memoizedState=y}}function Ed(a,l){if(typeof a!="function")throw Error(f(191,a));a.call(l)}function Od(a,l){var s=a.callbacks;if(s!==null)for(a.callbacks=null,a=0;a<s.length;a++)Ed(s[a],l)}var nn=xa(null),Jt=xa(0);function Dd(a,l){a=Ul,L(Jt,a),L(nn,l),Ul=a|l.baseLanes}function ji(){L(Jt,Ul),L(nn,nn.current)}function qi(){Ul=Jt.current,la(nn),la(Jt)}var Na=xa(null),Ia=null;function Kl(a){var l=a.alternate;L(ta,ta.current&1),L(Na,a),Ia===null&&(l===null||nn.current!==null||l.memoizedState!==null)&&(Ia=a)}function Gi(a){L(ta,ta.current),L(Na,a),Ia===null&&(Ia=a)}function Bd(a){a.tag===22?(L(ta,ta.current),L(Na,a),Ia===null&&(Ia=a)):Jl()}function Jl(){L(ta,ta.current),L(Na,Na.current)}function Ra(a){la(Na),Ia===a&&(Ia=null),la(ta)}var ta=xa(0);function Wt(a){for(var l=a;l!==null;){if(l.tag===13){var s=l.memoizedState;if(s!==null&&(s=s.dehydrated,s===null||Vc(s)||Kc(s)))return l}else if(l.tag===19&&(l.memoizedProps.revealOrder==="forwards"||l.memoizedProps.revealOrder==="backwards"||l.memoizedProps.revealOrder==="unstable_legacy-backwards"||l.memoizedProps.revealOrder==="together")){if((l.flags&128)!==0)return l}else if(l.child!==null){l.child.return=l,l=l.child;continue}if(l===a)break;for(;l.sibling===null;){if(l.return===null||l.return===a)return null;l=l.return}l.sibling.return=l.return,l=l.sibling}return null}var Al=0,O=null,V=null,ca=null,Ft=!1,tn=!1,Ts=!1,$t=0,Xn=0,en=null,qf=0;function sa(){throw Error(f(321))}function Yi(a,l){if(l===null)return!1;for(var s=0;s<l.length&&s<a.length;s++)if(!Ha(a[s],l[s]))return!1;return!0}function Zi(a,l,s,n,t,e){return Al=e,O=l,l.memoizedState=null,l.updateQueue=null,l.lanes=0,h.H=a===null||a.memoizedState===null?po:nc,Ts=!1,e=s(n,t),Ts=!1,tn&&(e=kd(l,s,n,t)),Ud(a),e}function Ud(a){h.H=Jn;var l=V!==null&&V.next!==null;if(Al=0,ca=V=O=null,Ft=!1,Xn=0,en=null,l)throw Error(f(300));a===null||ua||(a=a.dependencies,a!==null&&Yt(a)&&(ua=!0))}function kd(a,l,s,n){O=a;var t=0;do{if(tn&&(en=null),Xn=0,tn=!1,25<=t)throw Error(f(301));if(t+=1,ca=V=null,a.updateQueue!=null){var e=a.updateQueue;e.lastEffect=null,e.events=null,e.stores=null,e.memoCache!=null&&(e.memoCache.index=0)}h.H=mo,e=l(s,n)}while(tn);return e}function Gf(){var a=h.H,l=a.useState()[0];return l=typeof l.then=="function"?Vn(l):l,a=a.useState()[0],(V!==null?V.memoizedState:null)!==a&&(O.flags|=1024),l}function Li(){var a=$t!==0;return $t=0,a}function Qi(a,l,s){l.updateQueue=a.updateQueue,l.flags&=-2053,a.lanes&=~s}function Xi(a){if(Ft){for(a=a.memoizedState;a!==null;){var l=a.queue;l!==null&&(l.pending=null),a=a.next}Ft=!1}Al=0,ca=V=O=null,tn=!1,Xn=$t=0,en=null}function za(){var a={memoizedState:null,baseState:null,baseQueue:null,queue:null,next:null};return ca===null?O.memoizedState=ca=a:ca=ca.next=a,ca}function ea(){if(V===null){var a=O.alternate;a=a!==null?a.memoizedState:null}else a=V.next;var l=ca===null?O.memoizedState:ca.next;if(l!==null)ca=l,V=a;else{if(a===null)throw O.alternate===null?Error(f(467)):Error(f(310));V=a,a={memoizedState:V.memoizedState,baseState:V.baseState,baseQueue:V.baseQueue,queue:V.queue,next:null},ca===null?O.memoizedState=ca=a:ca=ca.next=a}return ca}function It(){return{lastEffect:null,events:null,stores:null,memoCache:null}}function Vn(a){var l=Xn;return Xn+=1,en===null&&(en=[]),a=zd(en,a,l),l=O,(ca===null?l.memoizedState:ca.next)===null&&(l=l.alternate,h.H=l===null||l.memoizedState===null?po:nc),a}function Pt(a){if(a!==null&&typeof a=="object"){if(typeof a.then=="function")return Vn(a);if(a.$$typeof===La)return ba(a)}throw Error(f(438,String(a)))}function Vi(a){var l=null,s=O.updateQueue;if(s!==null&&(l=s.memoCache),l==null){var n=O.alternate;n!==null&&(n=n.updateQueue,n!==null&&(n=n.memoCache,n!=null&&(l={data:n.data.map(function(t){return t.slice()}),index:0})))}if(l==null&&(l={data:[],index:0}),s===null&&(s=It(),O.updateQueue=s),s.memoCache=l,s=l.data[l.index],s===void 0)for(s=l.data[l.index]=Array(a),n=0;n<a;n++)s[n]=mt;return l.index++,s}function wl(a,l){return typeof l=="function"?l(a):l}function ae(a){var l=ea();return Ki(l,V,a)}function Ki(a,l,s){var n=a.queue;if(n===null)throw Error(f(311));n.lastRenderedReducer=s;var t=a.baseQueue,e=n.pending;if(e!==null){if(t!==null){var i=t.next;t.next=e.next,e.next=i}l.baseQueue=t=e,n.pending=null}if(e=a.baseState,t===null)a.memoizedState=e;else{l=t.next;var c=i=null,u=null,r=l,g=!1;do{var y=r.lane&-536870913;if(y!==r.lane?(R&y)===y:(Al&y)===y){var p=r.revertLane;if(p===0)u!==null&&(u=u.next={lane:0,revertLane:0,gesture:null,action:r.action,hasEagerState:r.hasEagerState,eagerState:r.eagerState,next:null}),y===Ps&&(g=!0);else if((Al&p)===p){r=r.next,p===Ps&&(g=!0);continue}else y={lane:0,revertLane:r.revertLane,gesture:null,action:r.action,hasEagerState:r.hasEagerState,eagerState:r.eagerState,next:null},u===null?(c=u=y,i=e):u=u.next=y,O.lanes|=p,$l|=p;y=r.action,Ts&&s(e,y),e=r.hasEagerState?r.eagerState:s(e,y)}else p={lane:y,revertLane:r.revertLane,gesture:r.gesture,action:r.action,hasEagerState:r.hasEagerState,eagerState:r.eagerState,next:null},u===null?(c=u=p,i=e):u=u.next=p,O.lanes|=y,$l|=y;r=r.next}while(r!==null&&r!==l);if(u===null?i=e:u.next=c,!Ha(e,a.memoizedState)&&(ua=!0,g&&(s=an,s!==null)))throw s;a.memoizedState=e,a.baseState=i,a.baseQueue=u,n.lastRenderedState=e}return t===null&&(n.lanes=0),[a.memoizedState,n.dispatch]}function Ji(a){var l=ea(),s=l.queue;if(s===null)throw Error(f(311));s.lastRenderedReducer=a;var n=s.dispatch,t=s.pending,e=l.memoizedState;if(t!==null){s.pending=null;var i=t=t.next;do e=a(e,i.action),i=i.next;while(i!==t);Ha(e,l.memoizedState)||(ua=!0),l.memoizedState=e,l.baseQueue===null&&(l.baseState=e),s.lastRenderedState=e}return[e,n]}function Cd(a,l,s){var n=O,t=ea(),e=q;if(e){if(s===void 0)throw Error(f(407));s=s()}else s=l();var i=!Ha((V||t).memoizedState,s);if(i&&(t.memoizedState=s,ua=!0),t=t.queue,$i(Nd.bind(null,n,t,a),[a]),t.getSnapshot!==l||i||ca!==null&&ca.memoizedState.tag&1){if(n.flags|=2048,cn(9,{destroy:void 0},_d.bind(null,n,t,s,l),null),W===null)throw Error(f(349));e||(Al&127)!==0||Hd(n,l,s)}return s}function Hd(a,l,s){a.flags|=16384,a={getSnapshot:l,value:s},l=O.updateQueue,l===null?(l=It(),O.updateQueue=l,l.stores=[a]):(s=l.stores,s===null?l.stores=[a]:s.push(a))}function _d(a,l,s,n){l.value=s,l.getSnapshot=n,Rd(l)&&jd(a)}function Nd(a,l,s){return s(function(){Rd(l)&&jd(a)})}function Rd(a){var l=a.getSnapshot;a=a.value;try{var s=l();return!Ha(a,s)}catch{return!0}}function jd(a){var l=gs(a,2);l!==null&&Ba(l,a,2)}function Wi(a){var l=za();if(typeof a=="function"){var s=a;if(a=s(),Ts){Rl(!0);try{s()}finally{Rl(!1)}}}return l.memoizedState=l.baseState=a,l.queue={pending:null,lanes:0,dispatch:null,lastRenderedReducer:wl,lastRenderedState:a},l}function qd(a,l,s,n){return a.baseState=s,Ki(a,V,typeof n=="function"?n:wl)}function Yf(a,l,s,n,t){if(ne(a))throw Error(f(485));if(a=l.action,a!==null){var e={payload:t,action:a,next:null,isTransition:!0,status:"pending",value:null,reason:null,listeners:[],then:function(i){e.listeners.push(i)}};h.T!==null?s(!0):e.isTransition=!1,n(e),s=l.pending,s===null?(e.next=l.pending=e,Gd(l,e)):(e.next=s.next,l.pending=s.next=e)}}function Gd(a,l){var s=l.action,n=l.payload,t=a.state;if(l.isTransition){var e=h.T,i={};h.T=i;try{var c=s(t,n),u=h.S;u!==null&&u(i,c),Yd(a,l,c)}catch(r){Fi(a,l,r)}finally{e!==null&&i.types!==null&&(e.types=i.types),h.T=e}}else try{e=s(t,n),Yd(a,l,e)}catch(r){Fi(a,l,r)}}function Yd(a,l,s){s!==null&&typeof s=="object"&&typeof s.then=="function"?s.then(function(n){Zd(a,l,n)},function(n){return Fi(a,l,n)}):Zd(a,l,s)}function Zd(a,l,s){l.status="fulfilled",l.value=s,Ld(l),a.state=s,l=a.pending,l!==null&&(s=l.next,s===l?a.pending=null:(s=s.next,l.next=s,Gd(a,s)))}function Fi(a,l,s){var n=a.pending;if(a.pending=null,n!==null){n=n.next;do l.status="rejected",l.reason=s,Ld(l),l=l.next;while(l!==n)}a.action=null}function Ld(a){a=a.listeners;for(var l=0;l<a.length;l++)(0,a[l])()}function Qd(a,l){return l}function Xd(a,l){if(q){var s=W.formState;if(s!==null){a:{var n=O;if(q){if(I){l:{for(var t=I,e=$a;t.nodeType!==8;){if(!e){t=null;break l}if(t=Pa(t.nextSibling),t===null){t=null;break l}}e=t.data,t=e==="F!"||e==="F"?t:null}if(t){I=Pa(t.nextSibling),n=t.data==="F!";break a}}Zl(n)}n=!1}n&&(l=s[0])}}return s=za(),s.memoizedState=s.baseState=l,n={pending:null,lanes:0,dispatch:null,lastRenderedReducer:Qd,lastRenderedState:l},s.queue=n,s=vo.bind(null,O,n),n.dispatch=s,n=Wi(!1),e=sc.bind(null,O,!1,n.queue),n=za(),t={state:l,dispatch:null,action:a,pending:null},n.queue=t,s=Yf.bind(null,O,t,e,s),t.dispatch=s,n.memoizedState=a,[l,s,!1]}function Vd(a){var l=ea();return Kd(l,V,a)}function Kd(a,l,s){if(l=Ki(a,l,Qd)[0],a=ae(wl)[0],typeof l=="object"&&l!==null&&typeof l.then=="function")try{var n=Vn(l)}catch(i){throw i===ln?Qt:i}else n=l;l=ea();var t=l.queue,e=t.dispatch;return s!==l.memoizedState&&(O.flags|=2048,cn(9,{destroy:void 0},Zf.bind(null,t,s),null)),[n,e,a]}function Zf(a,l){a.action=l}function Jd(a){var l=ea(),s=V;if(s!==null)return Kd(l,s,a);ea(),l=l.memoizedState,s=ea();var n=s.queue.dispatch;return s.memoizedState=a,[l,n,!1]}function cn(a,l,s,n){return a={tag:a,create:s,deps:n,inst:l,next:null},l=O.updateQueue,l===null&&(l=It(),O.updateQueue=l),s=l.lastEffect,s===null?l.lastEffect=a.next=a:(n=s.next,s.next=a,a.next=n,l.lastEffect=a),a}function Wd(){return ea().memoizedState}function le(a,l,s,n){var t=za();O.flags|=a,t.memoizedState=cn(1|l,{destroy:void 0},s,n===void 0?null:n)}function se(a,l,s,n){var t=ea();n=n===void 0?null:n;var e=t.memoizedState.inst;V!==null&&n!==null&&Yi(n,V.memoizedState.deps)?t.memoizedState=cn(l,e,s,n):(O.flags|=a,t.memoizedState=cn(1|l,e,s,n))}function Fd(a,l){le(8390656,8,a,l)}function $i(a,l){se(2048,8,a,l)}function Lf(a){O.flags|=4;var l=O.updateQueue;if(l===null)l=It(),O.updateQueue=l,l.events=[a];else{var s=l.events;s===null?l.events=[a]:s.push(a)}}function $d(a){var l=ea().memoizedState;return Lf({ref:l,nextImpl:a}),function(){if((Z&2)!==0)throw Error(f(440));return l.impl.apply(void 0,arguments)}}function Id(a,l){return se(4,2,a,l)}function Pd(a,l){return se(4,4,a,l)}function ao(a,l){if(typeof l=="function"){a=a();var s=l(a);return function(){typeof s=="function"?s():l(null)}}if(l!=null)return a=a(),l.current=a,function(){l.current=null}}function lo(a,l,s){s=s!=null?s.concat([a]):null,se(4,4,ao.bind(null,l,a),s)}function Ii(){}function so(a,l){var s=ea();l=l===void 0?null:l;var n=s.memoizedState;return l!==null&&Yi(l,n[1])?n[0]:(s.memoizedState=[a,l],a)}function no(a,l){var s=ea();l=l===void 0?null:l;var n=s.memoizedState;if(l!==null&&Yi(l,n[1]))return n[0];if(n=a(),Ts){Rl(!0);try{a()}finally{Rl(!1)}}return s.memoizedState=[n,l],n}function Pi(a,l,s){return s===void 0||(Al&1073741824)!==0&&(R&261930)===0?a.memoizedState=l:(a.memoizedState=s,a=ev(),O.lanes|=a,$l|=a,s)}function to(a,l,s,n){return Ha(s,l)?s:nn.current!==null?(a=Pi(a,s,n),Ha(a,l)||(ua=!0),a):(Al&42)===0||(Al&1073741824)!==0&&(R&261930)===0?(ua=!0,a.memoizedState=s):(a=ev(),O.lanes|=a,$l|=a,l)}function eo(a,l,s,n,t){var e=x.p;x.p=e!==0&&8>e?e:8;var i=h.T,c={};h.T=c,sc(a,!1,l,s);try{var u=t(),r=h.S;if(r!==null&&r(c,u),u!==null&&typeof u=="object"&&typeof u.then=="function"){var g=jf(u,n);Kn(a,l,g,Ga(a))}else Kn(a,l,n,Ga(a))}catch(y){Kn(a,l,{then:function(){},status:"rejected",reason:y},Ga())}finally{x.p=e,i!==null&&c.types!==null&&(i.types=c.types),h.T=i}}function Qf(){}function ac(a,l,s,n){if(a.tag!==5)throw Error(f(476));var t=io(a).queue;eo(a,t,l,M,s===null?Qf:function(){return co(a),s(n)})}function io(a){var l=a.memoizedState;if(l!==null)return l;l={memoizedState:M,baseState:M,baseQueue:null,queue:{pending:null,lanes:0,dispatch:null,lastRenderedReducer:wl,lastRenderedState:M},next:null};var s={};return l.next={memoizedState:s,baseState:s,baseQueue:null,queue:{pending:null,lanes:0,dispatch:null,lastRenderedReducer:wl,lastRenderedState:s},next:null},a.memoizedState=l,a=a.alternate,a!==null&&(a.memoizedState=l),l}function co(a){var l=io(a);l.next===null&&(l=a.alternate.memoizedState),Kn(a,l.next.queue,{},Ga())}function lc(){return ba(ot)}function uo(){return ea().memoizedState}function oo(){return ea().memoizedState}function Xf(a){for(var l=a.return;l!==null;){switch(l.tag){case 24:case 3:var s=Ga();a=Xl(s);var n=Vl(l,a,s);n!==null&&(Ba(n,l,s),Zn(n,l,s)),l={cache:Bi()},a.payload=l;return}l=l.return}}function Vf(a,l,s){var n=Ga();s={lane:n,revertLane:0,gesture:null,action:s,hasEagerState:!1,eagerState:null,next:null},ne(a)?ro(l,s):(s=yi(a,l,s,n),s!==null&&(Ba(s,a,n),fo(s,l,n)))}function vo(a,l,s){var n=Ga();Kn(a,l,s,n)}function Kn(a,l,s,n){var t={lane:n,revertLane:0,gesture:null,action:s,hasEagerState:!1,eagerState:null,next:null};if(ne(a))ro(l,t);else{var e=a.alternate;if(a.lanes===0&&(e===null||e.lanes===0)&&(e=l.lastRenderedReducer,e!==null))try{var i=l.lastRenderedState,c=e(i,s);if(t.hasEagerState=!0,t.eagerState=c,Ha(c,i))return Rt(a,l,t,0),W===null&&Nt(),!1}catch{}finally{}if(s=yi(a,l,t,n),s!==null)return Ba(s,a,n),fo(s,l,n),!0}return!1}function sc(a,l,s,n){if(n={lane:2,revertLane:Hc(),gesture:null,action:n,hasEagerState:!1,eagerState:null,next:null},ne(a)){if(l)throw Error(f(479))}else l=yi(a,s,n,2),l!==null&&Ba(l,a,2)}function ne(a){var l=a.alternate;return a===O||l!==null&&l===O}function ro(a,l){tn=Ft=!0;var s=a.pending;s===null?l.next=l:(l.next=s.next,s.next=l),a.pending=l}function fo(a,l,s){if((s&4194048)!==0){var n=l.lanes;n&=a.pendingLanes,s|=n,l.lanes=s,bu(a,s)}}var Jn={readContext:ba,use:Pt,useCallback:sa,useContext:sa,useEffect:sa,useImperativeHandle:sa,useLayoutEffect:sa,useInsertionEffect:sa,useMemo:sa,useReducer:sa,useRef:sa,useState:sa,useDebugValue:sa,useDeferredValue:sa,useTransition:sa,useSyncExternalStore:sa,useId:sa,useHostTransitionStatus:sa,useFormState:sa,useActionState:sa,useOptimistic:sa,useMemoCache:sa,useCacheRefresh:sa};Jn.useEffectEvent=sa;var po={readContext:ba,use:Pt,useCallback:function(a,l){return za().memoizedState=[a,l===void 0?null:l],a},useContext:ba,useEffect:Fd,useImperativeHandle:function(a,l,s){s=s!=null?s.concat([a]):null,le(4194308,4,ao.bind(null,l,a),s)},useLayoutEffect:function(a,l){return le(4194308,4,a,l)},useInsertionEffect:function(a,l){le(4,2,a,l)},useMemo:function(a,l){var s=za();l=l===void 0?null:l;var n=a();if(Ts){Rl(!0);try{a()}finally{Rl(!1)}}return s.memoizedState=[n,l],n},useReducer:function(a,l,s){var n=za();if(s!==void 0){var t=s(l);if(Ts){Rl(!0);try{s(l)}finally{Rl(!1)}}}else t=l;return n.memoizedState=n.baseState=t,a={pending:null,lanes:0,dispatch:null,lastRenderedReducer:a,lastRenderedState:t},n.queue=a,a=a.dispatch=Vf.bind(null,O,a),[n.memoizedState,a]},useRef:function(a){var l=za();return a={current:a},l.memoizedState=a},useState:function(a){a=Wi(a);var l=a.queue,s=vo.bind(null,O,l);return l.dispatch=s,[a.memoizedState,s]},useDebugValue:Ii,useDeferredValue:function(a,l){var s=za();return Pi(s,a,l)},useTransition:function(){var a=Wi(!1);return a=eo.bind(null,O,a.queue,!0,!1),za().memoizedState=a,[!1,a]},useSyncExternalStore:function(a,l,s){var n=O,t=za();if(q){if(s===void 0)throw Error(f(407));s=s()}else{if(s=l(),W===null)throw Error(f(349));(R&127)!==0||Hd(n,l,s)}t.memoizedState=s;var e={value:s,getSnapshot:l};return t.queue=e,Fd(Nd.bind(null,n,e,a),[a]),n.flags|=2048,cn(9,{destroy:void 0},_d.bind(null,n,e,s,l),null),s},useId:function(){var a=za(),l=W.identifierPrefix;if(q){var s=ol,n=dl;s=(n&~(1<<32-Ca(n)-1)).toString(32)+s,l="_"+l+"R_"+s,s=$t++,0<s&&(l+="H"+s.toString(32)),l+="_"}else s=qf++,l="_"+l+"r_"+s.toString(32)+"_";return a.memoizedState=l},useHostTransitionStatus:lc,useFormState:Xd,useActionState:Xd,useOptimistic:function(a){var l=za();l.memoizedState=l.baseState=a;var s={pending:null,lanes:0,dispatch:null,lastRenderedReducer:null,lastRenderedState:null};return l.queue=s,l=sc.bind(null,O,!0,s),s.dispatch=l,[a,l]},useMemoCache:Vi,useCacheRefresh:function(){return za().memoizedState=Xf.bind(null,O)},useEffectEvent:function(a){var l=za(),s={impl:a};return l.memoizedState=s,function(){if((Z&2)!==0)throw Error(f(440));return s.impl.apply(void 0,arguments)}}},nc={readContext:ba,use:Pt,useCallback:so,useContext:ba,useEffect:$i,useImperativeHandle:lo,useInsertionEffect:Id,useLayoutEffect:Pd,useMemo:no,useReducer:ae,useRef:Wd,useState:function(){return ae(wl)},useDebugValue:Ii,useDeferredValue:function(a,l){var s=ea();return to(s,V.memoizedState,a,l)},useTransition:function(){var a=ae(wl)[0],l=ea().memoizedState;return[typeof a=="boolean"?a:Vn(a),l]},useSyncExternalStore:Cd,useId:uo,useHostTransitionStatus:lc,useFormState:Vd,useActionState:Vd,useOptimistic:function(a,l){var s=ea();return qd(s,V,a,l)},useMemoCache:Vi,useCacheRefresh:oo};nc.useEffectEvent=$d;var mo={readContext:ba,use:Pt,useCallback:so,useContext:ba,useEffect:$i,useImperativeHandle:lo,useInsertionEffect:Id,useLayoutEffect:Pd,useMemo:no,useReducer:Ji,useRef:Wd,useState:function(){return Ji(wl)},useDebugValue:Ii,useDeferredValue:function(a,l){var s=ea();return V===null?Pi(s,a,l):to(s,V.memoizedState,a,l)},useTransition:function(){var a=Ji(wl)[0],l=ea().memoizedState;return[typeof a=="boolean"?a:Vn(a),l]},useSyncExternalStore:Cd,useId:uo,useHostTransitionStatus:lc,useFormState:Jd,useActionState:Jd,useOptimistic:function(a,l){var s=ea();return V!==null?qd(s,V,a,l):(s.baseState=a,[a,s.queue.dispatch])},useMemoCache:Vi,useCacheRefresh:oo};mo.useEffectEvent=$d;function tc(a,l,s,n){l=a.memoizedState,s=s(n,l),s=s==null?l:k({},l,s),a.memoizedState=s,a.lanes===0&&(a.updateQueue.baseState=s)}var ec={enqueueSetState:function(a,l,s){a=a._reactInternals;var n=Ga(),t=Xl(n);t.payload=l,s!=null&&(t.callback=s),l=Vl(a,t,n),l!==null&&(Ba(l,a,n),Zn(l,a,n))},enqueueReplaceState:function(a,l,s){a=a._reactInternals;var n=Ga(),t=Xl(n);t.tag=1,t.payload=l,s!=null&&(t.callback=s),l=Vl(a,t,n),l!==null&&(Ba(l,a,n),Zn(l,a,n))},enqueueForceUpdate:function(a,l){a=a._reactInternals;var s=Ga(),n=Xl(s);n.tag=2,l!=null&&(n.callback=l),l=Vl(a,n,s),l!==null&&(Ba(l,a,s),Zn(l,a,s))}};function go(a,l,s,n,t,e,i){return a=a.stateNode,typeof a.shouldComponentUpdate=="function"?a.shouldComponentUpdate(n,e,i):l.prototype&&l.prototype.isPureReactComponent?!Hn(s,n)||!Hn(t,e):!0}function bo(a,l,s,n){a=l.state,typeof l.componentWillReceiveProps=="function"&&l.componentWillReceiveProps(s,n),typeof l.UNSAFE_componentWillReceiveProps=="function"&&l.UNSAFE_componentWillReceiveProps(s,n),l.state!==a&&ec.enqueueReplaceState(l,l.state,null)}function Ms(a,l){var s=l;if("ref"in l){s={};for(var n in l)n!=="ref"&&(s[n]=l[n])}if(a=a.defaultProps){s===l&&(s=k({},s));for(var t in a)s[t]===void 0&&(s[t]=a[t])}return s}function ho(a){_t(a)}function yo(a){console.error(a)}function So(a){_t(a)}function te(a,l){try{var s=a.onUncaughtError;s(l.value,{componentStack:l.stack})}catch(n){setTimeout(function(){throw n})}}function xo(a,l,s){try{var n=a.onCaughtError;n(s.value,{componentStack:s.stack,errorBoundary:l.tag===1?l.stateNode:null})}catch(t){setTimeout(function(){throw t})}}function ic(a,l,s){return s=Xl(s),s.tag=3,s.payload={element:null},s.callback=function(){te(a,l)},s}function zo(a){return a=Xl(a),a.tag=3,a}function Ao(a,l,s,n){var t=s.type.getDerivedStateFromError;if(typeof t=="function"){var e=n.value;a.payload=function(){return t(e)},a.callback=function(){xo(l,s,n)}}var i=s.stateNode;i!==null&&typeof i.componentDidCatch=="function"&&(a.callback=function(){xo(l,s,n),typeof t!="function"&&(Il===null?Il=new Set([this]):Il.add(this));var c=n.stack;this.componentDidCatch(n.value,{componentStack:c!==null?c:""})})}function Kf(a,l,s,n,t){if(s.flags|=32768,n!==null&&typeof n=="object"&&typeof n.then=="function"){if(l=s.alternate,l!==null&&Is(l,s,t,!0),s=Na.current,s!==null){switch(s.tag){case 31:case 13:return Ia===null?ge():s.alternate===null&&na===0&&(na=3),s.flags&=-257,s.flags|=65536,s.lanes=t,n===Xt?s.flags|=16384:(l=s.updateQueue,l===null?s.updateQueue=new Set([n]):l.add(n),Uc(a,n,t)),!1;case 22:return s.flags|=65536,n===Xt?s.flags|=16384:(l=s.updateQueue,l===null?(l={transitions:null,markerInstances:null,retryQueue:new Set([n])},s.updateQueue=l):(s=l.retryQueue,s===null?l.retryQueue=new Set([n]):s.add(n)),Uc(a,n,t)),!1}throw Error(f(435,s.tag))}return Uc(a,n,t),ge(),!1}if(q)return l=Na.current,l!==null?((l.flags&65536)===0&&(l.flags|=256),l.flags|=65536,l.lanes=t,n!==Ti&&(a=Error(f(422),{cause:n}),Rn(Ja(a,s)))):(n!==Ti&&(l=Error(f(423),{cause:n}),Rn(Ja(l,s))),a=a.current.alternate,a.flags|=65536,t&=-t,a.lanes|=t,n=Ja(n,s),t=ic(a.stateNode,n,t),Ni(a,t),na!==4&&(na=2)),!1;var e=Error(f(520),{cause:n});if(e=Ja(e,s),st===null?st=[e]:st.push(e),na!==4&&(na=2),l===null)return!0;n=Ja(n,s),s=l;do{switch(s.tag){case 3:return s.flags|=65536,a=t&-t,s.lanes|=a,a=ic(s.stateNode,n,a),Ni(s,a),!1;case 1:if(l=s.type,e=s.stateNode,(s.flags&128)===0&&(typeof l.getDerivedStateFromError=="function"||e!==null&&typeof e.componentDidCatch=="function"&&(Il===null||!Il.has(e))))return s.flags|=65536,t&=-t,s.lanes|=t,t=zo(t),Ao(t,a,s,n),Ni(s,t),!1}s=s.return}while(s!==null);return!1}var cc=Error(f(461)),ua=!1;function ha(a,l,s,n){l.child=a===null?Md(l,null,s,n):ws(l,a.child,s,n)}function wo(a,l,s,n,t){s=s.render;var e=l.ref;if("ref"in n){var i={};for(var c in n)c!=="ref"&&(i[c]=n[c])}else i=n;return Ss(l),n=Zi(a,l,s,i,e,t),c=Li(),a!==null&&!ua?(Qi(a,l,t),Tl(a,l,t)):(q&&c&&Ai(l),l.flags|=1,ha(a,l,n,t),l.child)}function To(a,l,s,n,t){if(a===null){var e=s.type;return typeof e=="function"&&!Si(e)&&e.defaultProps===void 0&&s.compare===null?(l.tag=15,l.type=e,Mo(a,l,e,n,t)):(a=qt(s.type,null,n,l,l.mode,t),a.ref=l.ref,a.return=l,l.child=a)}if(e=a.child,!mc(a,t)){var i=e.memoizedProps;if(s=s.compare,s=s!==null?s:Hn,s(i,n)&&a.ref===l.ref)return Tl(a,l,t)}return l.flags|=1,a=yl(e,n),a.ref=l.ref,a.return=l,l.child=a}function Mo(a,l,s,n,t){if(a!==null){var e=a.memoizedProps;if(Hn(e,n)&&a.ref===l.ref)if(ua=!1,l.pendingProps=n=e,mc(a,t))(a.flags&131072)!==0&&(ua=!0);else return l.lanes=a.lanes,Tl(a,l,t)}return uc(a,l,s,n,t)}function Eo(a,l,s,n){var t=n.children,e=a!==null?a.memoizedState:null;if(a===null&&l.stateNode===null&&(l.stateNode={_visibility:1,_pendingMarkers:null,_retryCache:null,_transitions:null}),n.mode==="hidden"){if((l.flags&128)!==0){if(e=e!==null?e.baseLanes|s:s,a!==null){for(n=l.child=a.child,t=0;n!==null;)t=t|n.lanes|n.childLanes,n=n.sibling;n=t&~e}else n=0,l.child=null;return Oo(a,l,e,s,n)}if((s&536870912)!==0)l.memoizedState={baseLanes:0,cachePool:null},a!==null&&Lt(l,e!==null?e.cachePool:null),e!==null?Dd(l,e):ji(),Bd(l);else return n=l.lanes=536870912,Oo(a,l,e!==null?e.baseLanes|s:s,s,n)}else e!==null?(Lt(l,e.cachePool),Dd(l,e),Jl(),l.memoizedState=null):(a!==null&&Lt(l,null),ji(),Jl());return ha(a,l,t,s),l.child}function Wn(a,l){return a!==null&&a.tag===22||l.stateNode!==null||(l.stateNode={_visibility:1,_pendingMarkers:null,_retryCache:null,_transitions:null}),l.sibling}function Oo(a,l,s,n,t){var e=ki();return e=e===null?null:{parent:ia._currentValue,pool:e},l.memoizedState={baseLanes:s,cachePool:e},a!==null&&Lt(l,null),ji(),Bd(l),a!==null&&Is(a,l,n,!0),l.childLanes=t,null}function ee(a,l){return l=ce({mode:l.mode,children:l.children},a.mode),l.ref=a.ref,a.child=l,l.return=a,l}function Do(a,l,s){return ws(l,a.child,null,s),a=ee(l,l.pendingProps),a.flags|=2,Ra(l),l.memoizedState=null,a}function Jf(a,l,s){var n=l.pendingProps,t=(l.flags&128)!==0;if(l.flags&=-129,a===null){if(q){if(n.mode==="hidden")return a=ee(l,n),l.lanes=536870912,Wn(null,a);if(Gi(l),(a=I)?(a=Yv(a,$a),a=a!==null&&a.data==="&"?a:null,a!==null&&(l.memoizedState={dehydrated:a,treeContext:Gl!==null?{id:dl,overflow:ol}:null,retryLane:536870912,hydrationErrors:null},s=vd(a),s.return=l,l.child=s,ga=l,I=null)):a=null,a===null)throw Zl(l);return l.lanes=536870912,null}return ee(l,n)}var e=a.memoizedState;if(e!==null){var i=e.dehydrated;if(Gi(l),t)if(l.flags&256)l.flags&=-257,l=Do(a,l,s);else if(l.memoizedState!==null)l.child=a.child,l.flags|=128,l=null;else throw Error(f(558));else if(ua||Is(a,l,s,!1),t=(s&a.childLanes)!==0,ua||t){if(n=W,n!==null&&(i=hu(n,s),i!==0&&i!==e.retryLane))throw e.retryLane=i,gs(a,i),Ba(n,a,i),cc;ge(),l=Do(a,l,s)}else a=e.treeContext,I=Pa(i.nextSibling),ga=l,q=!0,Yl=null,$a=!1,a!==null&&pd(l,a),l=ee(l,n),l.flags|=4096;return l}return a=yl(a.child,{mode:n.mode,children:n.children}),a.ref=l.ref,l.child=a,a.return=l,a}function ie(a,l){var s=l.ref;if(s===null)a!==null&&a.ref!==null&&(l.flags|=4194816);else{if(typeof s!="function"&&typeof s!="object")throw Error(f(284));(a===null||a.ref!==s)&&(l.flags|=4194816)}}function uc(a,l,s,n,t){return Ss(l),s=Zi(a,l,s,n,void 0,t),n=Li(),a!==null&&!ua?(Qi(a,l,t),Tl(a,l,t)):(q&&n&&Ai(l),l.flags|=1,ha(a,l,s,t),l.child)}function Bo(a,l,s,n,t,e){return Ss(l),l.updateQueue=null,s=kd(l,n,s,t),Ud(a),n=Li(),a!==null&&!ua?(Qi(a,l,e),Tl(a,l,e)):(q&&n&&Ai(l),l.flags|=1,ha(a,l,s,e),l.child)}function Uo(a,l,s,n,t){if(Ss(l),l.stateNode===null){var e=Js,i=s.contextType;typeof i=="object"&&i!==null&&(e=ba(i)),e=new s(n,e),l.memoizedState=e.state!==null&&e.state!==void 0?e.state:null,e.updater=ec,l.stateNode=e,e._reactInternals=l,e=l.stateNode,e.props=n,e.state=l.memoizedState,e.refs={},Hi(l),i=s.contextType,e.context=typeof i=="object"&&i!==null?ba(i):Js,e.state=l.memoizedState,i=s.getDerivedStateFromProps,typeof i=="function"&&(tc(l,s,i,n),e.state=l.memoizedState),typeof s.getDerivedStateFromProps=="function"||typeof e.getSnapshotBeforeUpdate=="function"||typeof e.UNSAFE_componentWillMount!="function"&&typeof e.componentWillMount!="function"||(i=e.state,typeof e.componentWillMount=="function"&&e.componentWillMount(),typeof e.UNSAFE_componentWillMount=="function"&&e.UNSAFE_componentWillMount(),i!==e.state&&ec.enqueueReplaceState(e,e.state,null),Qn(l,n,e,t),Ln(),e.state=l.memoizedState),typeof e.componentDidMount=="function"&&(l.flags|=4194308),n=!0}else if(a===null){e=l.stateNode;var c=l.memoizedProps,u=Ms(s,c);e.props=u;var r=e.context,g=s.contextType;i=Js,typeof g=="object"&&g!==null&&(i=ba(g));var y=s.getDerivedStateFromProps;g=typeof y=="function"||typeof e.getSnapshotBeforeUpdate=="function",c=l.pendingProps!==c,g||typeof e.UNSAFE_componentWillReceiveProps!="function"&&typeof e.componentWillReceiveProps!="function"||(c||r!==i)&&bo(l,e,n,i),Ql=!1;var p=l.memoizedState;e.state=p,Qn(l,n,e,t),Ln(),r=l.memoizedState,c||p!==r||Ql?(typeof y=="function"&&(tc(l,s,y,n),r=l.memoizedState),(u=Ql||go(l,s,u,n,p,r,i))?(g||typeof e.UNSAFE_componentWillMount!="function"&&typeof e.componentWillMount!="function"||(typeof e.componentWillMount=="function"&&e.componentWillMount(),typeof e.UNSAFE_componentWillMount=="function"&&e.UNSAFE_componentWillMount()),typeof e.componentDidMount=="function"&&(l.flags|=4194308)):(typeof e.componentDidMount=="function"&&(l.flags|=4194308),l.memoizedProps=n,l.memoizedState=r),e.props=n,e.state=r,e.context=i,n=u):(typeof e.componentDidMount=="function"&&(l.flags|=4194308),n=!1)}else{e=l.stateNode,_i(a,l),i=l.memoizedProps,g=Ms(s,i),e.props=g,y=l.pendingProps,p=e.context,r=s.contextType,u=Js,typeof r=="object"&&r!==null&&(u=ba(r)),c=s.getDerivedStateFromProps,(r=typeof c=="function"||typeof e.getSnapshotBeforeUpdate=="function")||typeof e.UNSAFE_componentWillReceiveProps!="function"&&typeof e.componentWillReceiveProps!="function"||(i!==y||p!==u)&&bo(l,e,n,u),Ql=!1,p=l.memoizedState,e.state=p,Qn(l,n,e,t),Ln();var m=l.memoizedState;i!==y||p!==m||Ql||a!==null&&a.dependencies!==null&&Yt(a.dependencies)?(typeof c=="function"&&(tc(l,s,c,n),m=l.memoizedState),(g=Ql||go(l,s,g,n,p,m,u)||a!==null&&a.dependencies!==null&&Yt(a.dependencies))?(r||typeof e.UNSAFE_componentWillUpdate!="function"&&typeof e.componentWillUpdate!="function"||(typeof e.componentWillUpdate=="function"&&e.componentWillUpdate(n,m,u),typeof e.UNSAFE_componentWillUpdate=="function"&&e.UNSAFE_componentWillUpdate(n,m,u)),typeof e.componentDidUpdate=="function"&&(l.flags|=4),typeof e.getSnapshotBeforeUpdate=="function"&&(l.flags|=1024)):(typeof e.componentDidUpdate!="function"||i===a.memoizedProps&&p===a.memoizedState||(l.flags|=4),typeof e.getSnapshotBeforeUpdate!="function"||i===a.memoizedProps&&p===a.memoizedState||(l.flags|=1024),l.memoizedProps=n,l.memoizedState=m),e.props=n,e.state=m,e.context=u,n=g):(typeof e.componentDidUpdate!="function"||i===a.memoizedProps&&p===a.memoizedState||(l.flags|=4),typeof e.getSnapshotBeforeUpdate!="function"||i===a.memoizedProps&&p===a.memoizedState||(l.flags|=1024),n=!1)}return e=n,ie(a,l),n=(l.flags&128)!==0,e||n?(e=l.stateNode,s=n&&typeof s.getDerivedStateFromError!="function"?null:e.render(),l.flags|=1,a!==null&&n?(l.child=ws(l,a.child,null,t),l.child=ws(l,null,s,t)):ha(a,l,s,t),l.memoizedState=e.state,a=l.child):a=Tl(a,l,t),a}function ko(a,l,s,n){return hs(),l.flags|=256,ha(a,l,s,n),l.child}var dc={dehydrated:null,treeContext:null,retryLane:0,hydrationErrors:null};function oc(a){return{baseLanes:a,cachePool:Sd()}}function vc(a,l,s){return a=a!==null?a.childLanes&~s:0,l&&(a|=qa),a}function Co(a,l,s){var n=l.pendingProps,t=!1,e=(l.flags&128)!==0,i;if((i=e)||(i=a!==null&&a.memoizedState===null?!1:(ta.current&2)!==0),i&&(t=!0,l.flags&=-129),i=(l.flags&32)!==0,l.flags&=-33,a===null){if(q){if(t?Kl(l):Jl(),(a=I)?(a=Yv(a,$a),a=a!==null&&a.data!=="&"?a:null,a!==null&&(l.memoizedState={dehydrated:a,treeContext:Gl!==null?{id:dl,overflow:ol}:null,retryLane:536870912,hydrationErrors:null},s=vd(a),s.return=l,l.child=s,ga=l,I=null)):a=null,a===null)throw Zl(l);return Kc(a)?l.lanes=32:l.lanes=536870912,null}var c=n.children;return n=n.fallback,t?(Jl(),t=l.mode,c=ce({mode:"hidden",children:c},t),n=bs(n,t,s,null),c.return=l,n.return=l,c.sibling=n,l.child=c,n=l.child,n.memoizedState=oc(s),n.childLanes=vc(a,i,s),l.memoizedState=dc,Wn(null,n)):(Kl(l),rc(l,c))}var u=a.memoizedState;if(u!==null&&(c=u.dehydrated,c!==null)){if(e)l.flags&256?(Kl(l),l.flags&=-257,l=fc(a,l,s)):l.memoizedState!==null?(Jl(),l.child=a.child,l.flags|=128,l=null):(Jl(),c=n.fallback,t=l.mode,n=ce({mode:"visible",children:n.children},t),c=bs(c,t,s,null),c.flags|=2,n.return=l,c.return=l,n.sibling=c,l.child=n,ws(l,a.child,null,s),n=l.child,n.memoizedState=oc(s),n.childLanes=vc(a,i,s),l.memoizedState=dc,l=Wn(null,n));else if(Kl(l),Kc(c)){if(i=c.nextSibling&&c.nextSibling.dataset,i)var r=i.dgst;i=r,n=Error(f(419)),n.stack="",n.digest=i,Rn({value:n,source:null,stack:null}),l=fc(a,l,s)}else if(ua||Is(a,l,s,!1),i=(s&a.childLanes)!==0,ua||i){if(i=W,i!==null&&(n=hu(i,s),n!==0&&n!==u.retryLane))throw u.retryLane=n,gs(a,n),Ba(i,a,n),cc;Vc(c)||ge(),l=fc(a,l,s)}else Vc(c)?(l.flags|=192,l.child=a.child,l=null):(a=u.treeContext,I=Pa(c.nextSibling),ga=l,q=!0,Yl=null,$a=!1,a!==null&&pd(l,a),l=rc(l,n.children),l.flags|=4096);return l}return t?(Jl(),c=n.fallback,t=l.mode,u=a.child,r=u.sibling,n=yl(u,{mode:"hidden",children:n.children}),n.subtreeFlags=u.subtreeFlags&65011712,r!==null?c=yl(r,c):(c=bs(c,t,s,null),c.flags|=2),c.return=l,n.return=l,n.sibling=c,l.child=n,Wn(null,n),n=l.child,c=a.child.memoizedState,c===null?c=oc(s):(t=c.cachePool,t!==null?(u=ia._currentValue,t=t.parent!==u?{parent:u,pool:u}:t):t=Sd(),c={baseLanes:c.baseLanes|s,cachePool:t}),n.memoizedState=c,n.childLanes=vc(a,i,s),l.memoizedState=dc,Wn(a.child,n)):(Kl(l),s=a.child,a=s.sibling,s=yl(s,{mode:"visible",children:n.children}),s.return=l,s.sibling=null,a!==null&&(i=l.deletions,i===null?(l.deletions=[a],l.flags|=16):i.push(a)),l.child=s,l.memoizedState=null,s)}function rc(a,l){return l=ce({mode:"visible",children:l},a.mode),l.return=a,a.child=l}function ce(a,l){return a=_a(22,a,null,l),a.lanes=0,a}function fc(a,l,s){return ws(l,a.child,null,s),a=rc(l,l.pendingProps.children),a.flags|=2,l.memoizedState=null,a}function Ho(a,l,s){a.lanes|=l;var n=a.alternate;n!==null&&(n.lanes|=l),Oi(a.return,l,s)}function pc(a,l,s,n,t,e){var i=a.memoizedState;i===null?a.memoizedState={isBackwards:l,rendering:null,renderingStartTime:0,last:n,tail:s,tailMode:t,treeForkCount:e}:(i.isBackwards=l,i.rendering=null,i.renderingStartTime=0,i.last=n,i.tail=s,i.tailMode=t,i.treeForkCount=e)}function _o(a,l,s){var n=l.pendingProps,t=n.revealOrder,e=n.tail;n=n.children;var i=ta.current,c=(i&2)!==0;if(c?(i=i&1|2,l.flags|=128):i&=1,L(ta,i),ha(a,l,n,s),n=q?Nn:0,!c&&a!==null&&(a.flags&128)!==0)a:for(a=l.child;a!==null;){if(a.tag===13)a.memoizedState!==null&&Ho(a,s,l);else if(a.tag===19)Ho(a,s,l);else if(a.child!==null){a.child.return=a,a=a.child;continue}if(a===l)break a;for(;a.sibling===null;){if(a.return===null||a.return===l)break a;a=a.return}a.sibling.return=a.return,a=a.sibling}switch(t){case"forwards":for(s=l.child,t=null;s!==null;)a=s.alternate,a!==null&&Wt(a)===null&&(t=s),s=s.sibling;s=t,s===null?(t=l.child,l.child=null):(t=s.sibling,s.sibling=null),pc(l,!1,t,s,e,n);break;case"backwards":case"unstable_legacy-backwards":for(s=null,t=l.child,l.child=null;t!==null;){if(a=t.alternate,a!==null&&Wt(a)===null){l.child=t;break}a=t.sibling,t.sibling=s,s=t,t=a}pc(l,!0,s,null,e,n);break;case"together":pc(l,!1,null,null,void 0,n);break;default:l.memoizedState=null}return l.child}function Tl(a,l,s){if(a!==null&&(l.dependencies=a.dependencies),$l|=l.lanes,(s&l.childLanes)===0)if(a!==null){if(Is(a,l,s,!1),(s&l.childLanes)===0)return null}else return null;if(a!==null&&l.child!==a.child)throw Error(f(153));if(l.child!==null){for(a=l.child,s=yl(a,a.pendingProps),l.child=s,s.return=l;a.sibling!==null;)a=a.sibling,s=s.sibling=yl(a,a.pendingProps),s.return=l;s.sibling=null}return l.child}function mc(a,l){return(a.lanes&l)!==0?!0:(a=a.dependencies,!!(a!==null&&Yt(a)))}function Wf(a,l,s){switch(l.tag){case 3:ht(l,l.stateNode.containerInfo),Ll(l,ia,a.memoizedState.cache),hs();break;case 27:case 5:qe(l);break;case 4:ht(l,l.stateNode.containerInfo);break;case 10:Ll(l,l.type,l.memoizedProps.value);break;case 31:if(l.memoizedState!==null)return l.flags|=128,Gi(l),null;break;case 13:var n=l.memoizedState;if(n!==null)return n.dehydrated!==null?(Kl(l),l.flags|=128,null):(s&l.child.childLanes)!==0?Co(a,l,s):(Kl(l),a=Tl(a,l,s),a!==null?a.sibling:null);Kl(l);break;case 19:var t=(a.flags&128)!==0;if(n=(s&l.childLanes)!==0,n||(Is(a,l,s,!1),n=(s&l.childLanes)!==0),t){if(n)return _o(a,l,s);l.flags|=128}if(t=l.memoizedState,t!==null&&(t.rendering=null,t.tail=null,t.lastEffect=null),L(ta,ta.current),n)break;return null;case 22:return l.lanes=0,Eo(a,l,s,l.pendingProps);case 24:Ll(l,ia,a.memoizedState.cache)}return Tl(a,l,s)}function No(a,l,s){if(a!==null)if(a.memoizedProps!==l.pendingProps)ua=!0;else{if(!mc(a,s)&&(l.flags&128)===0)return ua=!1,Wf(a,l,s);ua=(a.flags&131072)!==0}else ua=!1,q&&(l.flags&1048576)!==0&&fd(l,Nn,l.index);switch(l.lanes=0,l.tag){case 16:a:{var n=l.pendingProps;if(a=zs(l.elementType),l.type=a,typeof a=="function")Si(a)?(n=Ms(a,n),l.tag=1,l=Uo(null,l,a,n,s)):(l.tag=0,l=uc(null,l,a,n,s));else{if(a!=null){var t=a.$$typeof;if(t===_l){l.tag=11,l=wo(null,l,a,n,s);break a}else if(t===pl){l.tag=14,l=To(null,l,a,n,s);break a}}throw l=xn(a)||a,Error(f(306,l,""))}}return l;case 0:return uc(a,l,l.type,l.pendingProps,s);case 1:return n=l.type,t=Ms(n,l.pendingProps),Uo(a,l,n,t,s);case 3:a:{if(ht(l,l.stateNode.containerInfo),a===null)throw Error(f(387));n=l.pendingProps;var e=l.memoizedState;t=e.element,_i(a,l),Qn(l,n,null,s);var i=l.memoizedState;if(n=i.cache,Ll(l,ia,n),n!==e.cache&&Di(l,[ia],s,!0),Ln(),n=i.element,e.isDehydrated)if(e={element:n,isDehydrated:!1,cache:i.cache},l.updateQueue.baseState=e,l.memoizedState=e,l.flags&256){l=ko(a,l,n,s);break a}else if(n!==t){t=Ja(Error(f(424)),l),Rn(t),l=ko(a,l,n,s);break a}else{switch(a=l.stateNode.containerInfo,a.nodeType){case 9:a=a.body;break;default:a=a.nodeName==="HTML"?a.ownerDocument.body:a}for(I=Pa(a.firstChild),ga=l,q=!0,Yl=null,$a=!0,s=Md(l,null,n,s),l.child=s;s;)s.flags=s.flags&-3|4096,s=s.sibling}else{if(hs(),n===t){l=Tl(a,l,s);break a}ha(a,l,n,s)}l=l.child}return l;case 26:return ie(a,l),a===null?(s=Kv(l.type,null,l.pendingProps,null))?l.memoizedState=s:q||(s=l.type,a=l.pendingProps,n=Ae(Nl.current).createElement(s),n[ma]=l,n[wa]=a,ya(n,s,a),fa(n),l.stateNode=n):l.memoizedState=Kv(l.type,a.memoizedProps,l.pendingProps,a.memoizedState),null;case 27:return qe(l),a===null&&q&&(n=l.stateNode=Qv(l.type,l.pendingProps,Nl.current),ga=l,$a=!0,t=I,ss(l.type)?(Jc=t,I=Pa(n.firstChild)):I=t),ha(a,l,l.pendingProps.children,s),ie(a,l),a===null&&(l.flags|=4194304),l.child;case 5:return a===null&&q&&((t=n=I)&&(n=Tp(n,l.type,l.pendingProps,$a),n!==null?(l.stateNode=n,ga=l,I=Pa(n.firstChild),$a=!1,t=!0):t=!1),t||Zl(l)),qe(l),t=l.type,e=l.pendingProps,i=a!==null?a.memoizedProps:null,n=e.children,Lc(t,e)?n=null:i!==null&&Lc(t,i)&&(l.flags|=32),l.memoizedState!==null&&(t=Zi(a,l,Gf,null,null,s),ot._currentValue=t),ie(a,l),ha(a,l,n,s),l.child;case 6:return a===null&&q&&((a=s=I)&&(s=Mp(s,l.pendingProps,$a),s!==null?(l.stateNode=s,ga=l,I=null,a=!0):a=!1),a||Zl(l)),null;case 13:return Co(a,l,s);case 4:return ht(l,l.stateNode.containerInfo),n=l.pendingProps,a===null?l.child=ws(l,null,n,s):ha(a,l,n,s),l.child;case 11:return wo(a,l,l.type,l.pendingProps,s);case 7:return ha(a,l,l.pendingProps,s),l.child;case 8:return ha(a,l,l.pendingProps.children,s),l.child;case 12:return ha(a,l,l.pendingProps.children,s),l.child;case 10:return n=l.pendingProps,Ll(l,l.type,n.value),ha(a,l,n.children,s),l.child;case 9:return t=l.type._context,n=l.pendingProps.children,Ss(l),t=ba(t),n=n(t),l.flags|=1,ha(a,l,n,s),l.child;case 14:return To(a,l,l.type,l.pendingProps,s);case 15:return Mo(a,l,l.type,l.pendingProps,s);case 19:return _o(a,l,s);case 31:return Jf(a,l,s);case 22:return Eo(a,l,s,l.pendingProps);case 24:return Ss(l),n=ba(ia),a===null?(t=ki(),t===null&&(t=W,e=Bi(),t.pooledCache=e,e.refCount++,e!==null&&(t.pooledCacheLanes|=s),t=e),l.memoizedState={parent:n,cache:t},Hi(l),Ll(l,ia,t)):((a.lanes&s)!==0&&(_i(a,l),Qn(l,null,null,s),Ln()),t=a.memoizedState,e=l.memoizedState,t.parent!==n?(t={parent:n,cache:n},l.memoizedState=t,l.lanes===0&&(l.memoizedState=l.updateQueue.baseState=t),Ll(l,ia,n)):(n=e.cache,Ll(l,ia,n),n!==t.cache&&Di(l,[ia],s,!0))),ha(a,l,l.pendingProps.children,s),l.child;case 29:throw l.pendingProps}throw Error(f(156,l.tag))}function Ml(a){a.flags|=4}function gc(a,l,s,n,t){if((l=(a.mode&32)!==0)&&(l=!1),l){if(a.flags|=16777216,(t&335544128)===t)if(a.stateNode.complete)a.flags|=8192;else if(dv())a.flags|=8192;else throw As=Xt,Ci}else a.flags&=-16777217}function Ro(a,l){if(l.type!=="stylesheet"||(l.state.loading&4)!==0)a.flags&=-16777217;else if(a.flags|=16777216,!Iv(l))if(dv())a.flags|=8192;else throw As=Xt,Ci}function ue(a,l){l!==null&&(a.flags|=4),a.flags&16384&&(l=a.tag!==22?mu():536870912,a.lanes|=l,vn|=l)}function Fn(a,l){if(!q)switch(a.tailMode){case"hidden":l=a.tail;for(var s=null;l!==null;)l.alternate!==null&&(s=l),l=l.sibling;s===null?a.tail=null:s.sibling=null;break;case"collapsed":s=a.tail;for(var n=null;s!==null;)s.alternate!==null&&(n=s),s=s.sibling;n===null?l||a.tail===null?a.tail=null:a.tail.sibling=null:n.sibling=null}}function P(a){var l=a.alternate!==null&&a.alternate.child===a.child,s=0,n=0;if(l)for(var t=a.child;t!==null;)s|=t.lanes|t.childLanes,n|=t.subtreeFlags&65011712,n|=t.flags&65011712,t.return=a,t=t.sibling;else for(t=a.child;t!==null;)s|=t.lanes|t.childLanes,n|=t.subtreeFlags,n|=t.flags,t.return=a,t=t.sibling;return a.subtreeFlags|=n,a.childLanes=s,l}function Ff(a,l,s){var n=l.pendingProps;switch(wi(l),l.tag){case 16:case 15:case 0:case 11:case 7:case 8:case 12:case 9:case 14:return P(l),null;case 1:return P(l),null;case 3:return s=l.stateNode,n=null,a!==null&&(n=a.memoizedState.cache),l.memoizedState.cache!==n&&(l.flags|=2048),zl(ia),Hs(),s.pendingContext&&(s.context=s.pendingContext,s.pendingContext=null),(a===null||a.child===null)&&($s(l)?Ml(l):a===null||a.memoizedState.isDehydrated&&(l.flags&256)===0||(l.flags|=1024,Mi())),P(l),null;case 26:var t=l.type,e=l.memoizedState;return a===null?(Ml(l),e!==null?(P(l),Ro(l,e)):(P(l),gc(l,t,null,n,s))):e?e!==a.memoizedState?(Ml(l),P(l),Ro(l,e)):(P(l),l.flags&=-16777217):(a=a.memoizedProps,a!==n&&Ml(l),P(l),gc(l,t,a,n,s)),null;case 27:if(yt(l),s=Nl.current,t=l.type,a!==null&&l.stateNode!=null)a.memoizedProps!==n&&Ml(l);else{if(!n){if(l.stateNode===null)throw Error(f(166));return P(l),null}a=ra.current,$s(l)?md(l):(a=Qv(t,n,s),l.stateNode=a,Ml(l))}return P(l),null;case 5:if(yt(l),t=l.type,a!==null&&l.stateNode!=null)a.memoizedProps!==n&&Ml(l);else{if(!n){if(l.stateNode===null)throw Error(f(166));return P(l),null}if(e=ra.current,$s(l))md(l);else{var i=Ae(Nl.current);switch(e){case 1:e=i.createElementNS("http://www.w3.org/2000/svg",t);break;case 2:e=i.createElementNS("http://www.w3.org/1998/Math/MathML",t);break;default:switch(t){case"svg":e=i.createElementNS("http://www.w3.org/2000/svg",t);break;case"math":e=i.createElementNS("http://www.w3.org/1998/Math/MathML",t);break;case"script":e=i.createElement("div"),e.innerHTML="<script><\/script>",e=e.removeChild(e.firstChild);break;case"select":e=typeof n.is=="string"?i.createElement("select",{is:n.is}):i.createElement("select"),n.multiple?e.multiple=!0:n.size&&(e.size=n.size);break;default:e=typeof n.is=="string"?i.createElement(t,{is:n.is}):i.createElement(t)}}e[ma]=l,e[wa]=n;a:for(i=l.child;i!==null;){if(i.tag===5||i.tag===6)e.appendChild(i.stateNode);else if(i.tag!==4&&i.tag!==27&&i.child!==null){i.child.return=i,i=i.child;continue}if(i===l)break a;for(;i.sibling===null;){if(i.return===null||i.return===l)break a;i=i.return}i.sibling.return=i.return,i=i.sibling}l.stateNode=e;a:switch(ya(e,t,n),t){case"button":case"input":case"select":case"textarea":n=!!n.autoFocus;break a;case"img":n=!0;break a;default:n=!1}n&&Ml(l)}}return P(l),gc(l,l.type,a===null?null:a.memoizedProps,l.pendingProps,s),null;case 6:if(a&&l.stateNode!=null)a.memoizedProps!==n&&Ml(l);else{if(typeof n!="string"&&l.stateNode===null)throw Error(f(166));if(a=Nl.current,$s(l)){if(a=l.stateNode,s=l.memoizedProps,n=null,t=ga,t!==null)switch(t.tag){case 27:case 5:n=t.memoizedProps}a[ma]=l,a=!!(a.nodeValue===s||n!==null&&n.suppressHydrationWarning===!0||Cv(a.nodeValue,s)),a||Zl(l,!0)}else a=Ae(a).createTextNode(n),a[ma]=l,l.stateNode=a}return P(l),null;case 31:if(s=l.memoizedState,a===null||a.memoizedState!==null){if(n=$s(l),s!==null){if(a===null){if(!n)throw Error(f(318));if(a=l.memoizedState,a=a!==null?a.dehydrated:null,!a)throw Error(f(557));a[ma]=l}else hs(),(l.flags&128)===0&&(l.memoizedState=null),l.flags|=4;P(l),a=!1}else s=Mi(),a!==null&&a.memoizedState!==null&&(a.memoizedState.hydrationErrors=s),a=!0;if(!a)return l.flags&256?(Ra(l),l):(Ra(l),null);if((l.flags&128)!==0)throw Error(f(558))}return P(l),null;case 13:if(n=l.memoizedState,a===null||a.memoizedState!==null&&a.memoizedState.dehydrated!==null){if(t=$s(l),n!==null&&n.dehydrated!==null){if(a===null){if(!t)throw Error(f(318));if(t=l.memoizedState,t=t!==null?t.dehydrated:null,!t)throw Error(f(317));t[ma]=l}else hs(),(l.flags&128)===0&&(l.memoizedState=null),l.flags|=4;P(l),t=!1}else t=Mi(),a!==null&&a.memoizedState!==null&&(a.memoizedState.hydrationErrors=t),t=!0;if(!t)return l.flags&256?(Ra(l),l):(Ra(l),null)}return Ra(l),(l.flags&128)!==0?(l.lanes=s,l):(s=n!==null,a=a!==null&&a.memoizedState!==null,s&&(n=l.child,t=null,n.alternate!==null&&n.alternate.memoizedState!==null&&n.alternate.memoizedState.cachePool!==null&&(t=n.alternate.memoizedState.cachePool.pool),e=null,n.memoizedState!==null&&n.memoizedState.cachePool!==null&&(e=n.memoizedState.cachePool.pool),e!==t&&(n.flags|=2048)),s!==a&&s&&(l.child.flags|=8192),ue(l,l.updateQueue),P(l),null);case 4:return Hs(),a===null&&jc(l.stateNode.containerInfo),P(l),null;case 10:return zl(l.type),P(l),null;case 19:if(la(ta),n=l.memoizedState,n===null)return P(l),null;if(t=(l.flags&128)!==0,e=n.rendering,e===null)if(t)Fn(n,!1);else{if(na!==0||a!==null&&(a.flags&128)!==0)for(a=l.child;a!==null;){if(e=Wt(a),e!==null){for(l.flags|=128,Fn(n,!1),a=e.updateQueue,l.updateQueue=a,ue(l,a),l.subtreeFlags=0,a=s,s=l.child;s!==null;)od(s,a),s=s.sibling;return L(ta,ta.current&1|2),q&&Sl(l,n.treeForkCount),l.child}a=a.sibling}n.tail!==null&&Ua()>fe&&(l.flags|=128,t=!0,Fn(n,!1),l.lanes=4194304)}else{if(!t)if(a=Wt(e),a!==null){if(l.flags|=128,t=!0,a=a.updateQueue,l.updateQueue=a,ue(l,a),Fn(n,!0),n.tail===null&&n.tailMode==="hidden"&&!e.alternate&&!q)return P(l),null}else 2*Ua()-n.renderingStartTime>fe&&s!==536870912&&(l.flags|=128,t=!0,Fn(n,!1),l.lanes=4194304);n.isBackwards?(e.sibling=l.child,l.child=e):(a=n.last,a!==null?a.sibling=e:l.child=e,n.last=e)}return n.tail!==null?(a=n.tail,n.rendering=a,n.tail=a.sibling,n.renderingStartTime=Ua(),a.sibling=null,s=ta.current,L(ta,t?s&1|2:s&1),q&&Sl(l,n.treeForkCount),a):(P(l),null);case 22:case 23:return Ra(l),qi(),n=l.memoizedState!==null,a!==null?a.memoizedState!==null!==n&&(l.flags|=8192):n&&(l.flags|=8192),n?(s&536870912)!==0&&(l.flags&128)===0&&(P(l),l.subtreeFlags&6&&(l.flags|=8192)):P(l),s=l.updateQueue,s!==null&&ue(l,s.retryQueue),s=null,a!==null&&a.memoizedState!==null&&a.memoizedState.cachePool!==null&&(s=a.memoizedState.cachePool.pool),n=null,l.memoizedState!==null&&l.memoizedState.cachePool!==null&&(n=l.memoizedState.cachePool.pool),n!==s&&(l.flags|=2048),a!==null&&la(xs),null;case 24:return s=null,a!==null&&(s=a.memoizedState.cache),l.memoizedState.cache!==s&&(l.flags|=2048),zl(ia),P(l),null;case 25:return null;case 30:return null}throw Error(f(156,l.tag))}function $f(a,l){switch(wi(l),l.tag){case 1:return a=l.flags,a&65536?(l.flags=a&-65537|128,l):null;case 3:return zl(ia),Hs(),a=l.flags,(a&65536)!==0&&(a&128)===0?(l.flags=a&-65537|128,l):null;case 26:case 27:case 5:return yt(l),null;case 31:if(l.memoizedState!==null){if(Ra(l),l.alternate===null)throw Error(f(340));hs()}return a=l.flags,a&65536?(l.flags=a&-65537|128,l):null;case 13:if(Ra(l),a=l.memoizedState,a!==null&&a.dehydrated!==null){if(l.alternate===null)throw Error(f(340));hs()}return a=l.flags,a&65536?(l.flags=a&-65537|128,l):null;case 19:return la(ta),null;case 4:return Hs(),null;case 10:return zl(l.type),null;case 22:case 23:return Ra(l),qi(),a!==null&&la(xs),a=l.flags,a&65536?(l.flags=a&-65537|128,l):null;case 24:return zl(ia),null;case 25:return null;default:return null}}function jo(a,l){switch(wi(l),l.tag){case 3:zl(ia),Hs();break;case 26:case 27:case 5:yt(l);break;case 4:Hs();break;case 31:l.memoizedState!==null&&Ra(l);break;case 13:Ra(l);break;case 19:la(ta);break;case 10:zl(l.type);break;case 22:case 23:Ra(l),qi(),a!==null&&la(xs);break;case 24:zl(ia)}}function $n(a,l){try{var s=l.updateQueue,n=s!==null?s.lastEffect:null;if(n!==null){var t=n.next;s=t;do{if((s.tag&a)===a){n=void 0;var e=s.create,i=s.inst;n=e(),i.destroy=n}s=s.next}while(s!==t)}}catch(c){X(l,l.return,c)}}function Wl(a,l,s){try{var n=l.updateQueue,t=n!==null?n.lastEffect:null;if(t!==null){var e=t.next;n=e;do{if((n.tag&a)===a){var i=n.inst,c=i.destroy;if(c!==void 0){i.destroy=void 0,t=l;var u=s,r=c;try{r()}catch(g){X(t,u,g)}}}n=n.next}while(n!==e)}}catch(g){X(l,l.return,g)}}function qo(a){var l=a.updateQueue;if(l!==null){var s=a.stateNode;try{Od(l,s)}catch(n){X(a,a.return,n)}}}function Go(a,l,s){s.props=Ms(a.type,a.memoizedProps),s.state=a.memoizedState;try{s.componentWillUnmount()}catch(n){X(a,l,n)}}function In(a,l){try{var s=a.ref;if(s!==null){switch(a.tag){case 26:case 27:case 5:var n=a.stateNode;break;case 30:n=a.stateNode;break;default:n=a.stateNode}typeof s=="function"?a.refCleanup=s(n):s.current=n}}catch(t){X(a,l,t)}}function vl(a,l){var s=a.ref,n=a.refCleanup;if(s!==null)if(typeof n=="function")try{n()}catch(t){X(a,l,t)}finally{a.refCleanup=null,a=a.alternate,a!=null&&(a.refCleanup=null)}else if(typeof s=="function")try{s(null)}catch(t){X(a,l,t)}else s.current=null}function Yo(a){var l=a.type,s=a.memoizedProps,n=a.stateNode;try{a:switch(l){case"button":case"input":case"select":case"textarea":s.autoFocus&&n.focus();break a;case"img":s.src?n.src=s.src:s.srcSet&&(n.srcset=s.srcSet)}}catch(t){X(a,a.return,t)}}function bc(a,l,s){try{var n=a.stateNode;yp(n,a.type,s,l),n[wa]=l}catch(t){X(a,a.return,t)}}function Zo(a){return a.tag===5||a.tag===3||a.tag===26||a.tag===27&&ss(a.type)||a.tag===4}function hc(a){a:for(;;){for(;a.sibling===null;){if(a.return===null||Zo(a.return))return null;a=a.return}for(a.sibling.return=a.return,a=a.sibling;a.tag!==5&&a.tag!==6&&a.tag!==18;){if(a.tag===27&&ss(a.type)||a.flags&2||a.child===null||a.tag===4)continue a;a.child.return=a,a=a.child}if(!(a.flags&2))return a.stateNode}}function yc(a,l,s){var n=a.tag;if(n===5||n===6)a=a.stateNode,l?(s.nodeType===9?s.body:s.nodeName==="HTML"?s.ownerDocument.body:s).insertBefore(a,l):(l=s.nodeType===9?s.body:s.nodeName==="HTML"?s.ownerDocument.body:s,l.appendChild(a),s=s._reactRootContainer,s!=null||l.onclick!==null||(l.onclick=bl));else if(n!==4&&(n===27&&ss(a.type)&&(s=a.stateNode,l=null),a=a.child,a!==null))for(yc(a,l,s),a=a.sibling;a!==null;)yc(a,l,s),a=a.sibling}function de(a,l,s){var n=a.tag;if(n===5||n===6)a=a.stateNode,l?s.insertBefore(a,l):s.appendChild(a);else if(n!==4&&(n===27&&ss(a.type)&&(s=a.stateNode),a=a.child,a!==null))for(de(a,l,s),a=a.sibling;a!==null;)de(a,l,s),a=a.sibling}function Lo(a){var l=a.stateNode,s=a.memoizedProps;try{for(var n=a.type,t=l.attributes;t.length;)l.removeAttributeNode(t[0]);ya(l,n,s),l[ma]=a,l[wa]=s}catch(e){X(a,a.return,e)}}var El=!1,da=!1,Sc=!1,Qo=typeof WeakSet=="function"?WeakSet:Set,pa=null;function If(a,l){if(a=a.containerInfo,Yc=Be,a=ld(a),fi(a)){if("selectionStart"in a)var s={start:a.selectionStart,end:a.selectionEnd};else a:{s=(s=a.ownerDocument)&&s.defaultView||window;var n=s.getSelection&&s.getSelection();if(n&&n.rangeCount!==0){s=n.anchorNode;var t=n.anchorOffset,e=n.focusNode;n=n.focusOffset;try{s.nodeType,e.nodeType}catch{s=null;break a}var i=0,c=-1,u=-1,r=0,g=0,y=a,p=null;l:for(;;){for(var m;y!==s||t!==0&&y.nodeType!==3||(c=i+t),y!==e||n!==0&&y.nodeType!==3||(u=i+n),y.nodeType===3&&(i+=y.nodeValue.length),(m=y.firstChild)!==null;)p=y,y=m;for(;;){if(y===a)break l;if(p===s&&++r===t&&(c=i),p===e&&++g===n&&(u=i),(m=y.nextSibling)!==null)break;y=p,p=y.parentNode}y=m}s=c===-1||u===-1?null:{start:c,end:u}}else s=null}s=s||{start:0,end:0}}else s=null;for(Zc={focusedElem:a,selectionRange:s},Be=!1,pa=l;pa!==null;)if(l=pa,a=l.child,(l.subtreeFlags&1028)!==0&&a!==null)a.return=l,pa=a;else for(;pa!==null;){switch(l=pa,e=l.alternate,a=l.flags,l.tag){case 0:if((a&4)!==0&&(a=l.updateQueue,a=a!==null?a.events:null,a!==null))for(s=0;s<a.length;s++)t=a[s],t.ref.impl=t.nextImpl;break;case 11:case 15:break;case 1:if((a&1024)!==0&&e!==null){a=void 0,s=l,t=e.memoizedProps,e=e.memoizedState,n=s.stateNode;try{var z=Ms(s.type,t);a=n.getSnapshotBeforeUpdate(z,e),n.__reactInternalSnapshotBeforeUpdate=a}catch(T){X(s,s.return,T)}}break;case 3:if((a&1024)!==0){if(a=l.stateNode.containerInfo,s=a.nodeType,s===9)Xc(a);else if(s===1)switch(a.nodeName){case"HEAD":case"HTML":case"BODY":Xc(a);break;default:a.textContent=""}}break;case 5:case 26:case 27:case 6:case 4:case 17:break;default:if((a&1024)!==0)throw Error(f(163))}if(a=l.sibling,a!==null){a.return=l.return,pa=a;break}pa=l.return}}function Xo(a,l,s){var n=s.flags;switch(s.tag){case 0:case 11:case 15:Dl(a,s),n&4&&$n(5,s);break;case 1:if(Dl(a,s),n&4)if(a=s.stateNode,l===null)try{a.componentDidMount()}catch(i){X(s,s.return,i)}else{var t=Ms(s.type,l.memoizedProps);l=l.memoizedState;try{a.componentDidUpdate(t,l,a.__reactInternalSnapshotBeforeUpdate)}catch(i){X(s,s.return,i)}}n&64&&qo(s),n&512&&In(s,s.return);break;case 3:if(Dl(a,s),n&64&&(a=s.updateQueue,a!==null)){if(l=null,s.child!==null)switch(s.child.tag){case 27:case 5:l=s.child.stateNode;break;case 1:l=s.child.stateNode}try{Od(a,l)}catch(i){X(s,s.return,i)}}break;case 27:l===null&&n&4&&Lo(s);case 26:case 5:Dl(a,s),l===null&&n&4&&Yo(s),n&512&&In(s,s.return);break;case 12:Dl(a,s);break;case 31:Dl(a,s),n&4&&Jo(a,s);break;case 13:Dl(a,s),n&4&&Wo(a,s),n&64&&(a=s.memoizedState,a!==null&&(a=a.dehydrated,a!==null&&(s=cp.bind(null,s),Ep(a,s))));break;case 22:if(n=s.memoizedState!==null||El,!n){l=l!==null&&l.memoizedState!==null||da,t=El;var e=da;El=n,(da=l)&&!e?Bl(a,s,(s.subtreeFlags&8772)!==0):Dl(a,s),El=t,da=e}break;case 30:break;default:Dl(a,s)}}function Vo(a){var l=a.alternate;l!==null&&(a.alternate=null,Vo(l)),a.child=null,a.deletions=null,a.sibling=null,a.tag===5&&(l=a.stateNode,l!==null&&Fe(l)),a.stateNode=null,a.return=null,a.dependencies=null,a.memoizedProps=null,a.memoizedState=null,a.pendingProps=null,a.stateNode=null,a.updateQueue=null}var aa=null,Ma=!1;function Ol(a,l,s){for(s=s.child;s!==null;)Ko(a,l,s),s=s.sibling}function Ko(a,l,s){if(ka&&typeof ka.onCommitFiberUnmount=="function")try{ka.onCommitFiberUnmount(zn,s)}catch{}switch(s.tag){case 26:da||vl(s,l),Ol(a,l,s),s.memoizedState?s.memoizedState.count--:s.stateNode&&(s=s.stateNode,s.parentNode.removeChild(s));break;case 27:da||vl(s,l);var n=aa,t=Ma;ss(s.type)&&(aa=s.stateNode,Ma=!1),Ol(a,l,s),ct(s.stateNode),aa=n,Ma=t;break;case 5:da||vl(s,l);case 6:if(n=aa,t=Ma,aa=null,Ol(a,l,s),aa=n,Ma=t,aa!==null)if(Ma)try{(aa.nodeType===9?aa.body:aa.nodeName==="HTML"?aa.ownerDocument.body:aa).removeChild(s.stateNode)}catch(e){X(s,l,e)}else try{aa.removeChild(s.stateNode)}catch(e){X(s,l,e)}break;case 18:aa!==null&&(Ma?(a=aa,qv(a.nodeType===9?a.body:a.nodeName==="HTML"?a.ownerDocument.body:a,s.stateNode),yn(a)):qv(aa,s.stateNode));break;case 4:n=aa,t=Ma,aa=s.stateNode.containerInfo,Ma=!0,Ol(a,l,s),aa=n,Ma=t;break;case 0:case 11:case 14:case 15:Wl(2,s,l),da||Wl(4,s,l),Ol(a,l,s);break;case 1:da||(vl(s,l),n=s.stateNode,typeof n.componentWillUnmount=="function"&&Go(s,l,n)),Ol(a,l,s);break;case 21:Ol(a,l,s);break;case 22:da=(n=da)||s.memoizedState!==null,Ol(a,l,s),da=n;break;default:Ol(a,l,s)}}function Jo(a,l){if(l.memoizedState===null&&(a=l.alternate,a!==null&&(a=a.memoizedState,a!==null))){a=a.dehydrated;try{yn(a)}catch(s){X(l,l.return,s)}}}function Wo(a,l){if(l.memoizedState===null&&(a=l.alternate,a!==null&&(a=a.memoizedState,a!==null&&(a=a.dehydrated,a!==null))))try{yn(a)}catch(s){X(l,l.return,s)}}function Pf(a){switch(a.tag){case 31:case 13:case 19:var l=a.stateNode;return l===null&&(l=a.stateNode=new Qo),l;case 22:return a=a.stateNode,l=a._retryCache,l===null&&(l=a._retryCache=new Qo),l;default:throw Error(f(435,a.tag))}}function oe(a,l){var s=Pf(a);l.forEach(function(n){if(!s.has(n)){s.add(n);var t=up.bind(null,a,n);n.then(t,t)}})}function Ea(a,l){var s=l.deletions;if(s!==null)for(var n=0;n<s.length;n++){var t=s[n],e=a,i=l,c=i;a:for(;c!==null;){switch(c.tag){case 27:if(ss(c.type)){aa=c.stateNode,Ma=!1;break a}break;case 5:aa=c.stateNode,Ma=!1;break a;case 3:case 4:aa=c.stateNode.containerInfo,Ma=!0;break a}c=c.return}if(aa===null)throw Error(f(160));Ko(e,i,t),aa=null,Ma=!1,e=t.alternate,e!==null&&(e.return=null),t.return=null}if(l.subtreeFlags&13886)for(l=l.child;l!==null;)Fo(l,a),l=l.sibling}var tl=null;function Fo(a,l){var s=a.alternate,n=a.flags;switch(a.tag){case 0:case 11:case 14:case 15:Ea(l,a),Oa(a),n&4&&(Wl(3,a,a.return),$n(3,a),Wl(5,a,a.return));break;case 1:Ea(l,a),Oa(a),n&512&&(da||s===null||vl(s,s.return)),n&64&&El&&(a=a.updateQueue,a!==null&&(n=a.callbacks,n!==null&&(s=a.shared.hiddenCallbacks,a.shared.hiddenCallbacks=s===null?n:s.concat(n))));break;case 26:var t=tl;if(Ea(l,a),Oa(a),n&512&&(da||s===null||vl(s,s.return)),n&4){var e=s!==null?s.memoizedState:null;if(n=a.memoizedState,s===null)if(n===null)if(a.stateNode===null){a:{n=a.type,s=a.memoizedProps,t=t.ownerDocument||t;l:switch(n){case"title":e=t.getElementsByTagName("title")[0],(!e||e[Tn]||e[ma]||e.namespaceURI==="http://www.w3.org/2000/svg"||e.hasAttribute("itemprop"))&&(e=t.createElement(n),t.head.insertBefore(e,t.querySelector("head > title"))),ya(e,n,s),e[ma]=a,fa(e),n=e;break a;case"link":var i=Fv("link","href",t).get(n+(s.href||""));if(i){for(var c=0;c<i.length;c++)if(e=i[c],e.getAttribute("href")===(s.href==null||s.href===""?null:s.href)&&e.getAttribute("rel")===(s.rel==null?null:s.rel)&&e.getAttribute("title")===(s.title==null?null:s.title)&&e.getAttribute("crossorigin")===(s.crossOrigin==null?null:s.crossOrigin)){i.splice(c,1);break l}}e=t.createElement(n),ya(e,n,s),t.head.appendChild(e);break;case"meta":if(i=Fv("meta","content",t).get(n+(s.content||""))){for(c=0;c<i.length;c++)if(e=i[c],e.getAttribute("content")===(s.content==null?null:""+s.content)&&e.getAttribute("name")===(s.name==null?null:s.name)&&e.getAttribute("property")===(s.property==null?null:s.property)&&e.getAttribute("http-equiv")===(s.httpEquiv==null?null:s.httpEquiv)&&e.getAttribute("charset")===(s.charSet==null?null:s.charSet)){i.splice(c,1);break l}}e=t.createElement(n),ya(e,n,s),t.head.appendChild(e);break;default:throw Error(f(468,n))}e[ma]=a,fa(e),n=e}a.stateNode=n}else $v(t,a.type,a.stateNode);else a.stateNode=Wv(t,n,a.memoizedProps);else e!==n?(e===null?s.stateNode!==null&&(s=s.stateNode,s.parentNode.removeChild(s)):e.count--,n===null?$v(t,a.type,a.stateNode):Wv(t,n,a.memoizedProps)):n===null&&a.stateNode!==null&&bc(a,a.memoizedProps,s.memoizedProps)}break;case 27:Ea(l,a),Oa(a),n&512&&(da||s===null||vl(s,s.return)),s!==null&&n&4&&bc(a,a.memoizedProps,s.memoizedProps);break;case 5:if(Ea(l,a),Oa(a),n&512&&(da||s===null||vl(s,s.return)),a.flags&32){t=a.stateNode;try{Ys(t,"")}catch(z){X(a,a.return,z)}}n&4&&a.stateNode!=null&&(t=a.memoizedProps,bc(a,t,s!==null?s.memoizedProps:t)),n&1024&&(Sc=!0);break;case 6:if(Ea(l,a),Oa(a),n&4){if(a.stateNode===null)throw Error(f(162));n=a.memoizedProps,s=a.stateNode;try{s.nodeValue=n}catch(z){X(a,a.return,z)}}break;case 3:if(Me=null,t=tl,tl=we(l.containerInfo),Ea(l,a),tl=t,Oa(a),n&4&&s!==null&&s.memoizedState.isDehydrated)try{yn(l.containerInfo)}catch(z){X(a,a.return,z)}Sc&&(Sc=!1,$o(a));break;case 4:n=tl,tl=we(a.stateNode.containerInfo),Ea(l,a),Oa(a),tl=n;break;case 12:Ea(l,a),Oa(a);break;case 31:Ea(l,a),Oa(a),n&4&&(n=a.updateQueue,n!==null&&(a.updateQueue=null,oe(a,n)));break;case 13:Ea(l,a),Oa(a),a.child.flags&8192&&a.memoizedState!==null!=(s!==null&&s.memoizedState!==null)&&(re=Ua()),n&4&&(n=a.updateQueue,n!==null&&(a.updateQueue=null,oe(a,n)));break;case 22:t=a.memoizedState!==null;var u=s!==null&&s.memoizedState!==null,r=El,g=da;if(El=r||t,da=g||u,Ea(l,a),da=g,El=r,Oa(a),n&8192)a:for(l=a.stateNode,l._visibility=t?l._visibility&-2:l._visibility|1,t&&(s===null||u||El||da||Es(a)),s=null,l=a;;){if(l.tag===5||l.tag===26){if(s===null){u=s=l;try{if(e=u.stateNode,t)i=e.style,typeof i.setProperty=="function"?i.setProperty("display","none","important"):i.display="none";else{c=u.stateNode;var y=u.memoizedProps.style,p=y!=null&&y.hasOwnProperty("display")?y.display:null;c.style.display=p==null||typeof p=="boolean"?"":(""+p).trim()}}catch(z){X(u,u.return,z)}}}else if(l.tag===6){if(s===null){u=l;try{u.stateNode.nodeValue=t?"":u.memoizedProps}catch(z){X(u,u.return,z)}}}else if(l.tag===18){if(s===null){u=l;try{var m=u.stateNode;t?Gv(m,!0):Gv(u.stateNode,!1)}catch(z){X(u,u.return,z)}}}else if((l.tag!==22&&l.tag!==23||l.memoizedState===null||l===a)&&l.child!==null){l.child.return=l,l=l.child;continue}if(l===a)break a;for(;l.sibling===null;){if(l.return===null||l.return===a)break a;s===l&&(s=null),l=l.return}s===l&&(s=null),l.sibling.return=l.return,l=l.sibling}n&4&&(n=a.updateQueue,n!==null&&(s=n.retryQueue,s!==null&&(n.retryQueue=null,oe(a,s))));break;case 19:Ea(l,a),Oa(a),n&4&&(n=a.updateQueue,n!==null&&(a.updateQueue=null,oe(a,n)));break;case 30:break;case 21:break;default:Ea(l,a),Oa(a)}}function Oa(a){var l=a.flags;if(l&2){try{for(var s,n=a.return;n!==null;){if(Zo(n)){s=n;break}n=n.return}if(s==null)throw Error(f(160));switch(s.tag){case 27:var t=s.stateNode,e=hc(a);de(a,e,t);break;case 5:var i=s.stateNode;s.flags&32&&(Ys(i,""),s.flags&=-33);var c=hc(a);de(a,c,i);break;case 3:case 4:var u=s.stateNode.containerInfo,r=hc(a);yc(a,r,u);break;default:throw Error(f(161))}}catch(g){X(a,a.return,g)}a.flags&=-3}l&4096&&(a.flags&=-4097)}function $o(a){if(a.subtreeFlags&1024)for(a=a.child;a!==null;){var l=a;$o(l),l.tag===5&&l.flags&1024&&l.stateNode.reset(),a=a.sibling}}function Dl(a,l){if(l.subtreeFlags&8772)for(l=l.child;l!==null;)Xo(a,l.alternate,l),l=l.sibling}function Es(a){for(a=a.child;a!==null;){var l=a;switch(l.tag){case 0:case 11:case 14:case 15:Wl(4,l,l.return),Es(l);break;case 1:vl(l,l.return);var s=l.stateNode;typeof s.componentWillUnmount=="function"&&Go(l,l.return,s),Es(l);break;case 27:ct(l.stateNode);case 26:case 5:vl(l,l.return),Es(l);break;case 22:l.memoizedState===null&&Es(l);break;case 30:Es(l);break;default:Es(l)}a=a.sibling}}function Bl(a,l,s){for(s=s&&(l.subtreeFlags&8772)!==0,l=l.child;l!==null;){var n=l.alternate,t=a,e=l,i=e.flags;switch(e.tag){case 0:case 11:case 15:Bl(t,e,s),$n(4,e);break;case 1:if(Bl(t,e,s),n=e,t=n.stateNode,typeof t.componentDidMount=="function")try{t.componentDidMount()}catch(r){X(n,n.return,r)}if(n=e,t=n.updateQueue,t!==null){var c=n.stateNode;try{var u=t.shared.hiddenCallbacks;if(u!==null)for(t.shared.hiddenCallbacks=null,t=0;t<u.length;t++)Ed(u[t],c)}catch(r){X(n,n.return,r)}}s&&i&64&&qo(e),In(e,e.return);break;case 27:Lo(e);case 26:case 5:Bl(t,e,s),s&&n===null&&i&4&&Yo(e),In(e,e.return);break;case 12:Bl(t,e,s);break;case 31:Bl(t,e,s),s&&i&4&&Jo(t,e);break;case 13:Bl(t,e,s),s&&i&4&&Wo(t,e);break;case 22:e.memoizedState===null&&Bl(t,e,s),In(e,e.return);break;case 30:break;default:Bl(t,e,s)}l=l.sibling}}function xc(a,l){var s=null;a!==null&&a.memoizedState!==null&&a.memoizedState.cachePool!==null&&(s=a.memoizedState.cachePool.pool),a=null,l.memoizedState!==null&&l.memoizedState.cachePool!==null&&(a=l.memoizedState.cachePool.pool),a!==s&&(a!=null&&a.refCount++,s!=null&&jn(s))}function zc(a,l){a=null,l.alternate!==null&&(a=l.alternate.memoizedState.cache),l=l.memoizedState.cache,l!==a&&(l.refCount++,a!=null&&jn(a))}function el(a,l,s,n){if(l.subtreeFlags&10256)for(l=l.child;l!==null;)Io(a,l,s,n),l=l.sibling}function Io(a,l,s,n){var t=l.flags;switch(l.tag){case 0:case 11:case 15:el(a,l,s,n),t&2048&&$n(9,l);break;case 1:el(a,l,s,n);break;case 3:el(a,l,s,n),t&2048&&(a=null,l.alternate!==null&&(a=l.alternate.memoizedState.cache),l=l.memoizedState.cache,l!==a&&(l.refCount++,a!=null&&jn(a)));break;case 12:if(t&2048){el(a,l,s,n),a=l.stateNode;try{var e=l.memoizedProps,i=e.id,c=e.onPostCommit;typeof c=="function"&&c(i,l.alternate===null?"mount":"update",a.passiveEffectDuration,-0)}catch(u){X(l,l.return,u)}}else el(a,l,s,n);break;case 31:el(a,l,s,n);break;case 13:el(a,l,s,n);break;case 23:break;case 22:e=l.stateNode,i=l.alternate,l.memoizedState!==null?e._visibility&2?el(a,l,s,n):Pn(a,l):e._visibility&2?el(a,l,s,n):(e._visibility|=2,un(a,l,s,n,(l.subtreeFlags&10256)!==0||!1)),t&2048&&xc(i,l);break;case 24:el(a,l,s,n),t&2048&&zc(l.alternate,l);break;default:el(a,l,s,n)}}function un(a,l,s,n,t){for(t=t&&((l.subtreeFlags&10256)!==0||!1),l=l.child;l!==null;){var e=a,i=l,c=s,u=n,r=i.flags;switch(i.tag){case 0:case 11:case 15:un(e,i,c,u,t),$n(8,i);break;case 23:break;case 22:var g=i.stateNode;i.memoizedState!==null?g._visibility&2?un(e,i,c,u,t):Pn(e,i):(g._visibility|=2,un(e,i,c,u,t)),t&&r&2048&&xc(i.alternate,i);break;case 24:un(e,i,c,u,t),t&&r&2048&&zc(i.alternate,i);break;default:un(e,i,c,u,t)}l=l.sibling}}function Pn(a,l){if(l.subtreeFlags&10256)for(l=l.child;l!==null;){var s=a,n=l,t=n.flags;switch(n.tag){case 22:Pn(s,n),t&2048&&xc(n.alternate,n);break;case 24:Pn(s,n),t&2048&&zc(n.alternate,n);break;default:Pn(s,n)}l=l.sibling}}var at=8192;function dn(a,l,s){if(a.subtreeFlags&at)for(a=a.child;a!==null;)Po(a,l,s),a=a.sibling}function Po(a,l,s){switch(a.tag){case 26:dn(a,l,s),a.flags&at&&a.memoizedState!==null&&qp(s,tl,a.memoizedState,a.memoizedProps);break;case 5:dn(a,l,s);break;case 3:case 4:var n=tl;tl=we(a.stateNode.containerInfo),dn(a,l,s),tl=n;break;case 22:a.memoizedState===null&&(n=a.alternate,n!==null&&n.memoizedState!==null?(n=at,at=16777216,dn(a,l,s),at=n):dn(a,l,s));break;default:dn(a,l,s)}}function av(a){var l=a.alternate;if(l!==null&&(a=l.child,a!==null)){l.child=null;do l=a.sibling,a.sibling=null,a=l;while(a!==null)}}function lt(a){var l=a.deletions;if((a.flags&16)!==0){if(l!==null)for(var s=0;s<l.length;s++){var n=l[s];pa=n,sv(n,a)}av(a)}if(a.subtreeFlags&10256)for(a=a.child;a!==null;)lv(a),a=a.sibling}function lv(a){switch(a.tag){case 0:case 11:case 15:lt(a),a.flags&2048&&Wl(9,a,a.return);break;case 3:lt(a);break;case 12:lt(a);break;case 22:var l=a.stateNode;a.memoizedState!==null&&l._visibility&2&&(a.return===null||a.return.tag!==13)?(l._visibility&=-3,ve(a)):lt(a);break;default:lt(a)}}function ve(a){var l=a.deletions;if((a.flags&16)!==0){if(l!==null)for(var s=0;s<l.length;s++){var n=l[s];pa=n,sv(n,a)}av(a)}for(a=a.child;a!==null;){switch(l=a,l.tag){case 0:case 11:case 15:Wl(8,l,l.return),ve(l);break;case 22:s=l.stateNode,s._visibility&2&&(s._visibility&=-3,ve(l));break;default:ve(l)}a=a.sibling}}function sv(a,l){for(;pa!==null;){var s=pa;switch(s.tag){case 0:case 11:case 15:Wl(8,s,l);break;case 23:case 22:if(s.memoizedState!==null&&s.memoizedState.cachePool!==null){var n=s.memoizedState.cachePool.pool;n!=null&&n.refCount++}break;case 24:jn(s.memoizedState.cache)}if(n=s.child,n!==null)n.return=s,pa=n;else a:for(s=a;pa!==null;){n=pa;var t=n.sibling,e=n.return;if(Vo(n),n===s){pa=null;break a}if(t!==null){t.return=e,pa=t;break a}pa=e}}}var ap={getCacheForType:function(a){var l=ba(ia),s=l.data.get(a);return s===void 0&&(s=a(),l.data.set(a,s)),s},cacheSignal:function(){return ba(ia).controller.signal}},lp=typeof WeakMap=="function"?WeakMap:Map,Z=0,W=null,H=null,R=0,Q=0,ja=null,Fl=!1,on=!1,Ac=!1,Ul=0,na=0,$l=0,Os=0,wc=0,qa=0,vn=0,st=null,Da=null,Tc=!1,re=0,nv=0,fe=1/0,pe=null,Il=null,oa=0,Pl=null,rn=null,kl=0,Mc=0,Ec=null,tv=null,nt=0,Oc=null;function Ga(){return(Z&2)!==0&&R!==0?R&-R:h.T!==null?Hc():yu()}function ev(){if(qa===0)if((R&536870912)===0||q){var a=zt;zt<<=1,(zt&3932160)===0&&(zt=262144),qa=a}else qa=536870912;return a=Na.current,a!==null&&(a.flags|=32),qa}function Ba(a,l,s){(a===W&&(Q===2||Q===9)||a.cancelPendingCommit!==null)&&(fn(a,0),as(a,R,qa,!1)),wn(a,s),((Z&2)===0||a!==W)&&(a===W&&((Z&2)===0&&(Os|=s),na===4&&as(a,R,qa,!1)),rl(a))}function iv(a,l,s){if((Z&6)!==0)throw Error(f(327));var n=!s&&(l&127)===0&&(l&a.expiredLanes)===0||An(a,l),t=n?tp(a,l):Bc(a,l,!0),e=n;do{if(t===0){on&&!n&&as(a,l,0,!1);break}else{if(s=a.current.alternate,e&&!sp(s)){t=Bc(a,l,!1),e=!1;continue}if(t===2){if(e=l,a.errorRecoveryDisabledLanes&e)var i=0;else i=a.pendingLanes&-536870913,i=i!==0?i:i&536870912?536870912:0;if(i!==0){l=i;a:{var c=a;t=st;var u=c.current.memoizedState.isDehydrated;if(u&&(fn(c,i).flags|=256),i=Bc(c,i,!1),i!==2){if(Ac&&!u){c.errorRecoveryDisabledLanes|=e,Os|=e,t=4;break a}e=Da,Da=t,e!==null&&(Da===null?Da=e:Da.push.apply(Da,e))}t=i}if(e=!1,t!==2)continue}}if(t===1){fn(a,0),as(a,l,0,!0);break}a:{switch(n=a,e=t,e){case 0:case 1:throw Error(f(345));case 4:if((l&4194048)!==l)break;case 6:as(n,l,qa,!Fl);break a;case 2:Da=null;break;case 3:case 5:break;default:throw Error(f(329))}if((l&62914560)===l&&(t=re+300-Ua(),10<t)){if(as(n,l,qa,!Fl),wt(n,0,!0)!==0)break a;kl=l,n.timeoutHandle=Rv(cv.bind(null,n,s,Da,pe,Tc,l,qa,Os,vn,Fl,e,"Throttled",-0,0),t);break a}cv(n,s,Da,pe,Tc,l,qa,Os,vn,Fl,e,null,-0,0)}}break}while(!0);rl(a)}function cv(a,l,s,n,t,e,i,c,u,r,g,y,p,m){if(a.timeoutHandle=-1,y=l.subtreeFlags,y&8192||(y&16785408)===16785408){y={stylesheets:null,count:0,imgCount:0,imgBytes:0,suspenseyImages:[],waitingForImages:!0,waitingForViewTransition:!1,unsuspend:bl},Po(l,e,y);var z=(e&62914560)===e?re-Ua():(e&4194048)===e?nv-Ua():0;if(z=Gp(y,z),z!==null){kl=e,a.cancelPendingCommit=z(mv.bind(null,a,l,e,s,n,t,i,c,u,g,y,null,p,m)),as(a,e,i,!r);return}}mv(a,l,e,s,n,t,i,c,u)}function sp(a){for(var l=a;;){var s=l.tag;if((s===0||s===11||s===15)&&l.flags&16384&&(s=l.updateQueue,s!==null&&(s=s.stores,s!==null)))for(var n=0;n<s.length;n++){var t=s[n],e=t.getSnapshot;t=t.value;try{if(!Ha(e(),t))return!1}catch{return!1}}if(s=l.child,l.subtreeFlags&16384&&s!==null)s.return=l,l=s;else{if(l===a)break;for(;l.sibling===null;){if(l.return===null||l.return===a)return!0;l=l.return}l.sibling.return=l.return,l=l.sibling}}return!0}function as(a,l,s,n){l&=~wc,l&=~Os,a.suspendedLanes|=l,a.pingedLanes&=~l,n&&(a.warmLanes|=l),n=a.expirationTimes;for(var t=l;0<t;){var e=31-Ca(t),i=1<<e;n[e]=-1,t&=~i}s!==0&&gu(a,s,l)}function me(){return(Z&6)===0?(tt(0),!1):!0}function Dc(){if(H!==null){if(Q===0)var a=H.return;else a=H,xl=ys=null,Xi(a),sn=null,Gn=0,a=H;for(;a!==null;)jo(a.alternate,a),a=a.return;H=null}}function fn(a,l){var s=a.timeoutHandle;s!==-1&&(a.timeoutHandle=-1,zp(s)),s=a.cancelPendingCommit,s!==null&&(a.cancelPendingCommit=null,s()),kl=0,Dc(),W=a,H=s=yl(a.current,null),R=l,Q=0,ja=null,Fl=!1,on=An(a,l),Ac=!1,vn=qa=wc=Os=$l=na=0,Da=st=null,Tc=!1,(l&8)!==0&&(l|=l&32);var n=a.entangledLanes;if(n!==0)for(a=a.entanglements,n&=l;0<n;){var t=31-Ca(n),e=1<<t;l|=a[t],n&=~e}return Ul=l,Nt(),s}function uv(a,l){O=null,h.H=Jn,l===ln||l===Qt?(l=Ad(),Q=3):l===Ci?(l=Ad(),Q=4):Q=l===cc?8:l!==null&&typeof l=="object"&&typeof l.then=="function"?6:1,ja=l,H===null&&(na=1,te(a,Ja(l,a.current)))}function dv(){var a=Na.current;return a===null?!0:(R&4194048)===R?Ia===null:(R&62914560)===R||(R&536870912)!==0?a===Ia:!1}function ov(){var a=h.H;return h.H=Jn,a===null?Jn:a}function vv(){var a=h.A;return h.A=ap,a}function ge(){na=4,Fl||(R&4194048)!==R&&Na.current!==null||(on=!0),($l&134217727)===0&&(Os&134217727)===0||W===null||as(W,R,qa,!1)}function Bc(a,l,s){var n=Z;Z|=2;var t=ov(),e=vv();(W!==a||R!==l)&&(pe=null,fn(a,l)),l=!1;var i=na;a:do try{if(Q!==0&&H!==null){var c=H,u=ja;switch(Q){case 8:Dc(),i=6;break a;case 3:case 2:case 9:case 6:Na.current===null&&(l=!0);var r=Q;if(Q=0,ja=null,pn(a,c,u,r),s&&on){i=0;break a}break;default:r=Q,Q=0,ja=null,pn(a,c,u,r)}}np(),i=na;break}catch(g){uv(a,g)}while(!0);return l&&a.shellSuspendCounter++,xl=ys=null,Z=n,h.H=t,h.A=e,H===null&&(W=null,R=0,Nt()),i}function np(){for(;H!==null;)rv(H)}function tp(a,l){var s=Z;Z|=2;var n=ov(),t=vv();W!==a||R!==l?(pe=null,fe=Ua()+500,fn(a,l)):on=An(a,l);a:do try{if(Q!==0&&H!==null){l=H;var e=ja;l:switch(Q){case 1:Q=0,ja=null,pn(a,l,e,1);break;case 2:case 9:if(xd(e)){Q=0,ja=null,fv(l);break}l=function(){Q!==2&&Q!==9||W!==a||(Q=7),rl(a)},e.then(l,l);break a;case 3:Q=7;break a;case 4:Q=5;break a;case 7:xd(e)?(Q=0,ja=null,fv(l)):(Q=0,ja=null,pn(a,l,e,7));break;case 5:var i=null;switch(H.tag){case 26:i=H.memoizedState;case 5:case 27:var c=H;if(i?Iv(i):c.stateNode.complete){Q=0,ja=null;var u=c.sibling;if(u!==null)H=u;else{var r=c.return;r!==null?(H=r,be(r)):H=null}break l}}Q=0,ja=null,pn(a,l,e,5);break;case 6:Q=0,ja=null,pn(a,l,e,6);break;case 8:Dc(),na=6;break a;default:throw Error(f(462))}}ep();break}catch(g){uv(a,g)}while(!0);return xl=ys=null,h.H=n,h.A=t,Z=s,H!==null?0:(W=null,R=0,Nt(),na)}function ep(){for(;H!==null&&!Er();)rv(H)}function rv(a){var l=No(a.alternate,a,Ul);a.memoizedProps=a.pendingProps,l===null?be(a):H=l}function fv(a){var l=a,s=l.alternate;switch(l.tag){case 15:case 0:l=Bo(s,l,l.pendingProps,l.type,void 0,R);break;case 11:l=Bo(s,l,l.pendingProps,l.type.render,l.ref,R);break;case 5:Xi(l);default:jo(s,l),l=H=od(l,Ul),l=No(s,l,Ul)}a.memoizedProps=a.pendingProps,l===null?be(a):H=l}function pn(a,l,s,n){xl=ys=null,Xi(l),sn=null,Gn=0;var t=l.return;try{if(Kf(a,t,l,s,R)){na=1,te(a,Ja(s,a.current)),H=null;return}}catch(e){if(t!==null)throw H=t,e;na=1,te(a,Ja(s,a.current)),H=null;return}l.flags&32768?(q||n===1?a=!0:on||(R&536870912)!==0?a=!1:(Fl=a=!0,(n===2||n===9||n===3||n===6)&&(n=Na.current,n!==null&&n.tag===13&&(n.flags|=16384))),pv(l,a)):be(l)}function be(a){var l=a;do{if((l.flags&32768)!==0){pv(l,Fl);return}a=l.return;var s=Ff(l.alternate,l,Ul);if(s!==null){H=s;return}if(l=l.sibling,l!==null){H=l;return}H=l=a}while(l!==null);na===0&&(na=5)}function pv(a,l){do{var s=$f(a.alternate,a);if(s!==null){s.flags&=32767,H=s;return}if(s=a.return,s!==null&&(s.flags|=32768,s.subtreeFlags=0,s.deletions=null),!l&&(a=a.sibling,a!==null)){H=a;return}H=a=s}while(a!==null);na=6,H=null}function mv(a,l,s,n,t,e,i,c,u){a.cancelPendingCommit=null;do he();while(oa!==0);if((Z&6)!==0)throw Error(f(327));if(l!==null){if(l===a.current)throw Error(f(177));if(e=l.lanes|l.childLanes,e|=hi,Rr(a,s,e,i,c,u),a===W&&(H=W=null,R=0),rn=l,Pl=a,kl=s,Mc=e,Ec=t,tv=n,(l.subtreeFlags&10256)!==0||(l.flags&10256)!==0?(a.callbackNode=null,a.callbackPriority=0,dp(St,function(){return Sv(),null})):(a.callbackNode=null,a.callbackPriority=0),n=(l.flags&13878)!==0,(l.subtreeFlags&13878)!==0||n){n=h.T,h.T=null,t=x.p,x.p=2,i=Z,Z|=4;try{If(a,l,s)}finally{Z=i,x.p=t,h.T=n}}oa=1,gv(),bv(),hv()}}function gv(){if(oa===1){oa=0;var a=Pl,l=rn,s=(l.flags&13878)!==0;if((l.subtreeFlags&13878)!==0||s){s=h.T,h.T=null;var n=x.p;x.p=2;var t=Z;Z|=4;try{Fo(l,a);var e=Zc,i=ld(a.containerInfo),c=e.focusedElem,u=e.selectionRange;if(i!==c&&c&&c.ownerDocument&&ad(c.ownerDocument.documentElement,c)){if(u!==null&&fi(c)){var r=u.start,g=u.end;if(g===void 0&&(g=r),"selectionStart"in c)c.selectionStart=r,c.selectionEnd=Math.min(g,c.value.length);else{var y=c.ownerDocument||document,p=y&&y.defaultView||window;if(p.getSelection){var m=p.getSelection(),z=c.textContent.length,T=Math.min(u.start,z),J=u.end===void 0?T:Math.min(u.end,z);!m.extend&&T>J&&(i=J,J=T,T=i);var o=Pu(c,T),d=Pu(c,J);if(o&&d&&(m.rangeCount!==1||m.anchorNode!==o.node||m.anchorOffset!==o.offset||m.focusNode!==d.node||m.focusOffset!==d.offset)){var v=y.createRange();v.setStart(o.node,o.offset),m.removeAllRanges(),T>J?(m.addRange(v),m.extend(d.node,d.offset)):(v.setEnd(d.node,d.offset),m.addRange(v))}}}}for(y=[],m=c;m=m.parentNode;)m.nodeType===1&&y.push({element:m,left:m.scrollLeft,top:m.scrollTop});for(typeof c.focus=="function"&&c.focus(),c=0;c<y.length;c++){var b=y[c];b.element.scrollLeft=b.left,b.element.scrollTop=b.top}}Be=!!Yc,Zc=Yc=null}finally{Z=t,x.p=n,h.T=s}}a.current=l,oa=2}}function bv(){if(oa===2){oa=0;var a=Pl,l=rn,s=(l.flags&8772)!==0;if((l.subtreeFlags&8772)!==0||s){s=h.T,h.T=null;var n=x.p;x.p=2;var t=Z;Z|=4;try{Xo(a,l.alternate,l)}finally{Z=t,x.p=n,h.T=s}}oa=3}}function hv(){if(oa===4||oa===3){oa=0,Or();var a=Pl,l=rn,s=kl,n=tv;(l.subtreeFlags&10256)!==0||(l.flags&10256)!==0?oa=5:(oa=0,rn=Pl=null,yv(a,a.pendingLanes));var t=a.pendingLanes;if(t===0&&(Il=null),Je(s),l=l.stateNode,ka&&typeof ka.onCommitFiberRoot=="function")try{ka.onCommitFiberRoot(zn,l,void 0,(l.current.flags&128)===128)}catch{}if(n!==null){l=h.T,t=x.p,x.p=2,h.T=null;try{for(var e=a.onRecoverableError,i=0;i<n.length;i++){var c=n[i];e(c.value,{componentStack:c.stack})}}finally{h.T=l,x.p=t}}(kl&3)!==0&&he(),rl(a),t=a.pendingLanes,(s&261930)!==0&&(t&42)!==0?a===Oc?nt++:(nt=0,Oc=a):nt=0,tt(0)}}function yv(a,l){(a.pooledCacheLanes&=l)===0&&(l=a.pooledCache,l!=null&&(a.pooledCache=null,jn(l)))}function he(){return gv(),bv(),hv(),Sv()}function Sv(){if(oa!==5)return!1;var a=Pl,l=Mc;Mc=0;var s=Je(kl),n=h.T,t=x.p;try{x.p=32>s?32:s,h.T=null,s=Ec,Ec=null;var e=Pl,i=kl;if(oa=0,rn=Pl=null,kl=0,(Z&6)!==0)throw Error(f(331));var c=Z;if(Z|=4,lv(e.current),Io(e,e.current,i,s),Z=c,tt(0,!1),ka&&typeof ka.onPostCommitFiberRoot=="function")try{ka.onPostCommitFiberRoot(zn,e)}catch{}return!0}finally{x.p=t,h.T=n,yv(a,l)}}function xv(a,l,s){l=Ja(s,l),l=ic(a.stateNode,l,2),a=Vl(a,l,2),a!==null&&(wn(a,2),rl(a))}function X(a,l,s){if(a.tag===3)xv(a,a,s);else for(;l!==null;){if(l.tag===3){xv(l,a,s);break}else if(l.tag===1){var n=l.stateNode;if(typeof l.type.getDerivedStateFromError=="function"||typeof n.componentDidCatch=="function"&&(Il===null||!Il.has(n))){a=Ja(s,a),s=zo(2),n=Vl(l,s,2),n!==null&&(Ao(s,n,l,a),wn(n,2),rl(n));break}}l=l.return}}function Uc(a,l,s){var n=a.pingCache;if(n===null){n=a.pingCache=new lp;var t=new Set;n.set(l,t)}else t=n.get(l),t===void 0&&(t=new Set,n.set(l,t));t.has(s)||(Ac=!0,t.add(s),a=ip.bind(null,a,l,s),l.then(a,a))}function ip(a,l,s){var n=a.pingCache;n!==null&&n.delete(l),a.pingedLanes|=a.suspendedLanes&s,a.warmLanes&=~s,W===a&&(R&s)===s&&(na===4||na===3&&(R&62914560)===R&&300>Ua()-re?(Z&2)===0&&fn(a,0):wc|=s,vn===R&&(vn=0)),rl(a)}function zv(a,l){l===0&&(l=mu()),a=gs(a,l),a!==null&&(wn(a,l),rl(a))}function cp(a){var l=a.memoizedState,s=0;l!==null&&(s=l.retryLane),zv(a,s)}function up(a,l){var s=0;switch(a.tag){case 31:case 13:var n=a.stateNode,t=a.memoizedState;t!==null&&(s=t.retryLane);break;case 19:n=a.stateNode;break;case 22:n=a.stateNode._retryCache;break;default:throw Error(f(314))}n!==null&&n.delete(l),zv(a,s)}function dp(a,l){return Qe(a,l)}var ye=null,mn=null,kc=!1,Se=!1,Cc=!1,ls=0;function rl(a){a!==mn&&a.next===null&&(mn===null?ye=mn=a:mn=mn.next=a),Se=!0,kc||(kc=!0,vp())}function tt(a,l){if(!Cc&&Se){Cc=!0;do for(var s=!1,n=ye;n!==null;){if(a!==0){var t=n.pendingLanes;if(t===0)var e=0;else{var i=n.suspendedLanes,c=n.pingedLanes;e=(1<<31-Ca(42|a)+1)-1,e&=t&~(i&~c),e=e&201326741?e&201326741|1:e?e|2:0}e!==0&&(s=!0,Mv(n,e))}else e=R,e=wt(n,n===W?e:0,n.cancelPendingCommit!==null||n.timeoutHandle!==-1),(e&3)===0||An(n,e)||(s=!0,Mv(n,e));n=n.next}while(s);Cc=!1}}function op(){Av()}function Av(){Se=kc=!1;var a=0;ls!==0&&xp()&&(a=ls);for(var l=Ua(),s=null,n=ye;n!==null;){var t=n.next,e=wv(n,l);e===0?(n.next=null,s===null?ye=t:s.next=t,t===null&&(mn=s)):(s=n,(a!==0||(e&3)!==0)&&(Se=!0)),n=t}oa!==0&&oa!==5||tt(a),ls!==0&&(ls=0)}function wv(a,l){for(var s=a.suspendedLanes,n=a.pingedLanes,t=a.expirationTimes,e=a.pendingLanes&-62914561;0<e;){var i=31-Ca(e),c=1<<i,u=t[i];u===-1?((c&s)===0||(c&n)!==0)&&(t[i]=Nr(c,l)):u<=l&&(a.expiredLanes|=c),e&=~c}if(l=W,s=R,s=wt(a,a===l?s:0,a.cancelPendingCommit!==null||a.timeoutHandle!==-1),n=a.callbackNode,s===0||a===l&&(Q===2||Q===9)||a.cancelPendingCommit!==null)return n!==null&&n!==null&&Xe(n),a.callbackNode=null,a.callbackPriority=0;if((s&3)===0||An(a,s)){if(l=s&-s,l===a.callbackPriority)return l;switch(n!==null&&Xe(n),Je(s)){case 2:case 8:s=fu;break;case 32:s=St;break;case 268435456:s=pu;break;default:s=St}return n=Tv.bind(null,a),s=Qe(s,n),a.callbackPriority=l,a.callbackNode=s,l}return n!==null&&n!==null&&Xe(n),a.callbackPriority=2,a.callbackNode=null,2}function Tv(a,l){if(oa!==0&&oa!==5)return a.callbackNode=null,a.callbackPriority=0,null;var s=a.callbackNode;if(he()&&a.callbackNode!==s)return null;var n=R;return n=wt(a,a===W?n:0,a.cancelPendingCommit!==null||a.timeoutHandle!==-1),n===0?null:(iv(a,n,l),wv(a,Ua()),a.callbackNode!=null&&a.callbackNode===s?Tv.bind(null,a):null)}function Mv(a,l){if(he())return null;iv(a,l,!0)}function vp(){Ap(function(){(Z&6)!==0?Qe(ru,op):Av()})}function Hc(){if(ls===0){var a=Ps;a===0&&(a=xt,xt<<=1,(xt&261888)===0&&(xt=256)),ls=a}return ls}function Ev(a){return a==null||typeof a=="symbol"||typeof a=="boolean"?null:typeof a=="function"?a:Ot(""+a)}function Ov(a,l){var s=l.ownerDocument.createElement("input");return s.name=l.name,s.value=l.value,a.id&&s.setAttribute("form",a.id),l.parentNode.insertBefore(s,l),a=new FormData(a),s.parentNode.removeChild(s),a}function rp(a,l,s,n,t){if(l==="submit"&&s&&s.stateNode===t){var e=Ev((t[wa]||null).action),i=n.submitter;i&&(l=(l=i[wa]||null)?Ev(l.formAction):i.getAttribute("formAction"),l!==null&&(e=l,i=null));var c=new kt("action","action",null,n,t);a.push({event:c,listeners:[{instance:null,listener:function(){if(n.defaultPrevented){if(ls!==0){var u=i?Ov(t,i):new FormData(t);ac(s,{pending:!0,data:u,method:t.method,action:e},null,u)}}else typeof e=="function"&&(c.preventDefault(),u=i?Ov(t,i):new FormData(t),ac(s,{pending:!0,data:u,method:t.method,action:e},e,u))},currentTarget:t}]})}}for(var _c=0;_c<bi.length;_c++){var Nc=bi[_c],fp=Nc.toLowerCase(),pp=Nc[0].toUpperCase()+Nc.slice(1);nl(fp,"on"+pp)}nl(td,"onAnimationEnd"),nl(ed,"onAnimationIteration"),nl(id,"onAnimationStart"),nl("dblclick","onDoubleClick"),nl("focusin","onFocus"),nl("focusout","onBlur"),nl(Bf,"onTransitionRun"),nl(Uf,"onTransitionStart"),nl(kf,"onTransitionCancel"),nl(cd,"onTransitionEnd"),qs("onMouseEnter",["mouseout","mouseover"]),qs("onMouseLeave",["mouseout","mouseover"]),qs("onPointerEnter",["pointerout","pointerover"]),qs("onPointerLeave",["pointerout","pointerover"]),rs("onChange","change click focusin focusout input keydown keyup selectionchange".split(" ")),rs("onSelect","focusout contextmenu dragend focusin keydown keyup mousedown mouseup selectionchange".split(" ")),rs("onBeforeInput",["compositionend","keypress","textInput","paste"]),rs("onCompositionEnd","compositionend focusout keydown keypress keyup mousedown".split(" ")),rs("onCompositionStart","compositionstart focusout keydown keypress keyup mousedown".split(" ")),rs("onCompositionUpdate","compositionupdate focusout keydown keypress keyup mousedown".split(" "));var et="abort canplay canplaythrough durationchange emptied encrypted ended error loadeddata loadedmetadata loadstart pause play playing progress ratechange resize seeked seeking stalled suspend timeupdate volumechange waiting".split(" "),mp=new Set("beforetoggle cancel close invalid load scroll scrollend toggle".split(" ").concat(et));function Dv(a,l){l=(l&4)!==0;for(var s=0;s<a.length;s++){var n=a[s],t=n.event;n=n.listeners;a:{var e=void 0;if(l)for(var i=n.length-1;0<=i;i--){var c=n[i],u=c.instance,r=c.currentTarget;if(c=c.listener,u!==e&&t.isPropagationStopped())break a;e=c,t.currentTarget=r;try{e(t)}catch(g){_t(g)}t.currentTarget=null,e=u}else for(i=0;i<n.length;i++){if(c=n[i],u=c.instance,r=c.currentTarget,c=c.listener,u!==e&&t.isPropagationStopped())break a;e=c,t.currentTarget=r;try{e(t)}catch(g){_t(g)}t.currentTarget=null,e=u}}}}function _(a,l){var s=l[We];s===void 0&&(s=l[We]=new Set);var n=a+"__bubble";s.has(n)||(Bv(l,a,2,!1),s.add(n))}function Rc(a,l,s){var n=0;l&&(n|=4),Bv(s,a,n,l)}var xe="_reactListening"+Math.random().toString(36).slice(2);function jc(a){if(!a[xe]){a[xe]=!0,zu.forEach(function(s){s!=="selectionchange"&&(mp.has(s)||Rc(s,!1,a),Rc(s,!0,a))});var l=a.nodeType===9?a:a.ownerDocument;l===null||l[xe]||(l[xe]=!0,Rc("selectionchange",!1,l))}}function Bv(a,l,s,n){switch(er(l)){case 2:var t=Lp;break;case 8:t=Qp;break;default:t=Pc}s=t.bind(null,l,s,a),t=void 0,!ti||l!=="touchstart"&&l!=="touchmove"&&l!=="wheel"||(t=!0),n?t!==void 0?a.addEventListener(l,s,{capture:!0,passive:t}):a.addEventListener(l,s,!0):t!==void 0?a.addEventListener(l,s,{passive:t}):a.addEventListener(l,s,!1)}function qc(a,l,s,n,t){var e=n;if((l&1)===0&&(l&2)===0&&n!==null)a:for(;;){if(n===null)return;var i=n.tag;if(i===3||i===4){var c=n.stateNode.containerInfo;if(c===t)break;if(i===4)for(i=n.return;i!==null;){var u=i.tag;if((u===3||u===4)&&i.stateNode.containerInfo===t)return;i=i.return}for(;c!==null;){if(i=Ns(c),i===null)return;if(u=i.tag,u===5||u===6||u===26||u===27){n=e=i;continue a}c=c.parentNode}}n=n.return}Hu(function(){var r=e,g=si(s),y=[];a:{var p=ud.get(a);if(p!==void 0){var m=kt,z=a;switch(a){case"keypress":if(Bt(s)===0)break a;case"keydown":case"keyup":m=uf;break;case"focusin":z="focus",m=ui;break;case"focusout":z="blur",m=ui;break;case"beforeblur":case"afterblur":m=ui;break;case"click":if(s.button===2)break a;case"auxclick":case"dblclick":case"mousedown":case"mousemove":case"mouseup":case"mouseout":case"mouseover":case"contextmenu":m=Ru;break;case"drag":case"dragend":case"dragenter":case"dragexit":case"dragleave":case"dragover":case"dragstart":case"drop":m=Wr;break;case"touchcancel":case"touchend":case"touchmove":case"touchstart":m=vf;break;case td:case ed:case id:m=Ir;break;case cd:m=ff;break;case"scroll":case"scrollend":m=Kr;break;case"wheel":m=mf;break;case"copy":case"cut":case"paste":m=af;break;case"gotpointercapture":case"lostpointercapture":case"pointercancel":case"pointerdown":case"pointermove":case"pointerout":case"pointerover":case"pointerup":m=qu;break;case"toggle":case"beforetoggle":m=bf}var T=(l&4)!==0,J=!T&&(a==="scroll"||a==="scrollend"),o=T?p!==null?p+"Capture":null:p;T=[];for(var d=r,v;d!==null;){var b=d;if(v=b.stateNode,b=b.tag,b!==5&&b!==26&&b!==27||v===null||o===null||(b=En(d,o),b!=null&&T.push(it(d,b,v))),J)break;d=d.return}0<T.length&&(p=new m(p,z,null,s,g),y.push({event:p,listeners:T}))}}if((l&7)===0){a:{if(p=a==="mouseover"||a==="pointerover",m=a==="mouseout"||a==="pointerout",p&&s!==li&&(z=s.relatedTarget||s.fromElement)&&(Ns(z)||z[_s]))break a;if((m||p)&&(p=g.window===g?g:(p=g.ownerDocument)?p.defaultView||p.parentWindow:window,m?(z=s.relatedTarget||s.toElement,m=r,z=z?Ns(z):null,z!==null&&(J=C(z),T=z.tag,z!==J||T!==5&&T!==27&&T!==6)&&(z=null)):(m=null,z=r),m!==z)){if(T=Ru,b="onMouseLeave",o="onMouseEnter",d="mouse",(a==="pointerout"||a==="pointerover")&&(T=qu,b="onPointerLeave",o="onPointerEnter",d="pointer"),J=m==null?p:Mn(m),v=z==null?p:Mn(z),p=new T(b,d+"leave",m,s,g),p.target=J,p.relatedTarget=v,b=null,Ns(g)===r&&(T=new T(o,d+"enter",z,s,g),T.target=v,T.relatedTarget=J,b=T),J=b,m&&z)l:{for(T=gp,o=m,d=z,v=0,b=o;b;b=T(b))v++;b=0;for(var w=d;w;w=T(w))b++;for(;0<v-b;)o=T(o),v--;for(;0<b-v;)d=T(d),b--;for(;v--;){if(o===d||d!==null&&o===d.alternate){T=o;break l}o=T(o),d=T(d)}T=null}else T=null;m!==null&&Uv(y,p,m,T,!1),z!==null&&J!==null&&Uv(y,J,z,T,!0)}}a:{if(p=r?Mn(r):window,m=p.nodeName&&p.nodeName.toLowerCase(),m==="select"||m==="input"&&p.type==="file")var G=Ku;else if(Xu(p))if(Ju)G=Ef;else{G=Tf;var A=wf}else m=p.nodeName,!m||m.toLowerCase()!=="input"||p.type!=="checkbox"&&p.type!=="radio"?r&&ai(r.elementType)&&(G=Ku):G=Mf;if(G&&(G=G(a,r))){Vu(y,G,s,g);break a}A&&A(a,p,r),a==="focusout"&&r&&p.type==="number"&&r.memoizedProps.value!=null&&Pe(p,"number",p.value)}switch(A=r?Mn(r):window,a){case"focusin":(Xu(A)||A.contentEditable==="true")&&(Xs=A,pi=r,_n=null);break;case"focusout":_n=pi=Xs=null;break;case"mousedown":mi=!0;break;case"contextmenu":case"mouseup":case"dragend":mi=!1,sd(y,s,g);break;case"selectionchange":if(Df)break;case"keydown":case"keyup":sd(y,s,g)}var B;if(oi)a:{switch(a){case"compositionstart":var j="onCompositionStart";break a;case"compositionend":j="onCompositionEnd";break a;case"compositionupdate":j="onCompositionUpdate";break a}j=void 0}else Qs?Lu(a,s)&&(j="onCompositionEnd"):a==="keydown"&&s.keyCode===229&&(j="onCompositionStart");j&&(Gu&&s.locale!=="ko"&&(Qs||j!=="onCompositionStart"?j==="onCompositionEnd"&&Qs&&(B=_u()):(ql=g,ei="value"in ql?ql.value:ql.textContent,Qs=!0)),A=ze(r,j),0<A.length&&(j=new ju(j,a,null,s,g),y.push({event:j,listeners:A}),B?j.data=B:(B=Qu(s),B!==null&&(j.data=B)))),(B=yf?Sf(a,s):xf(a,s))&&(j=ze(r,"onBeforeInput"),0<j.length&&(A=new ju("onBeforeInput","beforeinput",null,s,g),y.push({event:A,listeners:j}),A.data=B)),rp(y,a,r,s,g)}Dv(y,l)})}function it(a,l,s){return{instance:a,listener:l,currentTarget:s}}function ze(a,l){for(var s=l+"Capture",n=[];a!==null;){var t=a,e=t.stateNode;if(t=t.tag,t!==5&&t!==26&&t!==27||e===null||(t=En(a,s),t!=null&&n.unshift(it(a,t,e)),t=En(a,l),t!=null&&n.push(it(a,t,e))),a.tag===3)return n;a=a.return}return[]}function gp(a){if(a===null)return null;do a=a.return;while(a&&a.tag!==5&&a.tag!==27);return a||null}function Uv(a,l,s,n,t){for(var e=l._reactName,i=[];s!==null&&s!==n;){var c=s,u=c.alternate,r=c.stateNode;if(c=c.tag,u!==null&&u===n)break;c!==5&&c!==26&&c!==27||r===null||(u=r,t?(r=En(s,e),r!=null&&i.unshift(it(s,r,u))):t||(r=En(s,e),r!=null&&i.push(it(s,r,u)))),s=s.return}i.length!==0&&a.push({event:l,listeners:i})}var bp=/\r\n?/g,hp=/\u0000|\uFFFD/g;function kv(a){return(typeof a=="string"?a:""+a).replace(bp,`
`).replace(hp,"")}function Cv(a,l){return l=kv(l),kv(a)===l}function K(a,l,s,n,t,e){switch(s){case"children":typeof n=="string"?l==="body"||l==="textarea"&&n===""||Ys(a,n):(typeof n=="number"||typeof n=="bigint")&&l!=="body"&&Ys(a,""+n);break;case"className":Mt(a,"class",n);break;case"tabIndex":Mt(a,"tabindex",n);break;case"dir":case"role":case"viewBox":case"width":case"height":Mt(a,s,n);break;case"style":ku(a,n,e);break;case"data":if(l!=="object"){Mt(a,"data",n);break}case"src":case"href":if(n===""&&(l!=="a"||s!=="href")){a.removeAttribute(s);break}if(n==null||typeof n=="function"||typeof n=="symbol"||typeof n=="boolean"){a.removeAttribute(s);break}n=Ot(""+n),a.setAttribute(s,n);break;case"action":case"formAction":if(typeof n=="function"){a.setAttribute(s,"javascript:throw new Error('A React form was unexpectedly submitted. If you called form.submit() manually, consider using form.requestSubmit() instead. If you\\'re trying to use event.stopPropagation() in a submit event handler, consider also calling event.preventDefault().')");break}else typeof e=="function"&&(s==="formAction"?(l!=="input"&&K(a,l,"name",t.name,t,null),K(a,l,"formEncType",t.formEncType,t,null),K(a,l,"formMethod",t.formMethod,t,null),K(a,l,"formTarget",t.formTarget,t,null)):(K(a,l,"encType",t.encType,t,null),K(a,l,"method",t.method,t,null),K(a,l,"target",t.target,t,null)));if(n==null||typeof n=="symbol"||typeof n=="boolean"){a.removeAttribute(s);break}n=Ot(""+n),a.setAttribute(s,n);break;case"onClick":n!=null&&(a.onclick=bl);break;case"onScroll":n!=null&&_("scroll",a);break;case"onScrollEnd":n!=null&&_("scrollend",a);break;case"dangerouslySetInnerHTML":if(n!=null){if(typeof n!="object"||!("__html"in n))throw Error(f(61));if(s=n.__html,s!=null){if(t.children!=null)throw Error(f(60));a.innerHTML=s}}break;case"multiple":a.multiple=n&&typeof n!="function"&&typeof n!="symbol";break;case"muted":a.muted=n&&typeof n!="function"&&typeof n!="symbol";break;case"suppressContentEditableWarning":case"suppressHydrationWarning":case"defaultValue":case"defaultChecked":case"innerHTML":case"ref":break;case"autoFocus":break;case"xlinkHref":if(n==null||typeof n=="function"||typeof n=="boolean"||typeof n=="symbol"){a.removeAttribute("xlink:href");break}s=Ot(""+n),a.setAttributeNS("http://www.w3.org/1999/xlink","xlink:href",s);break;case"contentEditable":case"spellCheck":case"draggable":case"value":case"autoReverse":case"externalResourcesRequired":case"focusable":case"preserveAlpha":n!=null&&typeof n!="function"&&typeof n!="symbol"?a.setAttribute(s,""+n):a.removeAttribute(s);break;case"inert":case"allowFullScreen":case"async":case"autoPlay":case"controls":case"default":case"defer":case"disabled":case"disablePictureInPicture":case"disableRemotePlayback":case"formNoValidate":case"hidden":case"loop":case"noModule":case"noValidate":case"open":case"playsInline":case"readOnly":case"required":case"reversed":case"scoped":case"seamless":case"itemScope":n&&typeof n!="function"&&typeof n!="symbol"?a.setAttribute(s,""):a.removeAttribute(s);break;case"capture":case"download":n===!0?a.setAttribute(s,""):n!==!1&&n!=null&&typeof n!="function"&&typeof n!="symbol"?a.setAttribute(s,n):a.removeAttribute(s);break;case"cols":case"rows":case"size":case"span":n!=null&&typeof n!="function"&&typeof n!="symbol"&&!isNaN(n)&&1<=n?a.setAttribute(s,n):a.removeAttribute(s);break;case"rowSpan":case"start":n==null||typeof n=="function"||typeof n=="symbol"||isNaN(n)?a.removeAttribute(s):a.setAttribute(s,n);break;case"popover":_("beforetoggle",a),_("toggle",a),Tt(a,"popover",n);break;case"xlinkActuate":gl(a,"http://www.w3.org/1999/xlink","xlink:actuate",n);break;case"xlinkArcrole":gl(a,"http://www.w3.org/1999/xlink","xlink:arcrole",n);break;case"xlinkRole":gl(a,"http://www.w3.org/1999/xlink","xlink:role",n);break;case"xlinkShow":gl(a,"http://www.w3.org/1999/xlink","xlink:show",n);break;case"xlinkTitle":gl(a,"http://www.w3.org/1999/xlink","xlink:title",n);break;case"xlinkType":gl(a,"http://www.w3.org/1999/xlink","xlink:type",n);break;case"xmlBase":gl(a,"http://www.w3.org/XML/1998/namespace","xml:base",n);break;case"xmlLang":gl(a,"http://www.w3.org/XML/1998/namespace","xml:lang",n);break;case"xmlSpace":gl(a,"http://www.w3.org/XML/1998/namespace","xml:space",n);break;case"is":Tt(a,"is",n);break;case"innerText":case"textContent":break;default:(!(2<s.length)||s[0]!=="o"&&s[0]!=="O"||s[1]!=="n"&&s[1]!=="N")&&(s=Xr.get(s)||s,Tt(a,s,n))}}function Gc(a,l,s,n,t,e){switch(s){case"style":ku(a,n,e);break;case"dangerouslySetInnerHTML":if(n!=null){if(typeof n!="object"||!("__html"in n))throw Error(f(61));if(s=n.__html,s!=null){if(t.children!=null)throw Error(f(60));a.innerHTML=s}}break;case"children":typeof n=="string"?Ys(a,n):(typeof n=="number"||typeof n=="bigint")&&Ys(a,""+n);break;case"onScroll":n!=null&&_("scroll",a);break;case"onScrollEnd":n!=null&&_("scrollend",a);break;case"onClick":n!=null&&(a.onclick=bl);break;case"suppressContentEditableWarning":case"suppressHydrationWarning":case"innerHTML":case"ref":break;case"innerText":case"textContent":break;default:if(!Au.hasOwnProperty(s))a:{if(s[0]==="o"&&s[1]==="n"&&(t=s.endsWith("Capture"),l=s.slice(2,t?s.length-7:void 0),e=a[wa]||null,e=e!=null?e[s]:null,typeof e=="function"&&a.removeEventListener(l,e,t),typeof n=="function")){typeof e!="function"&&e!==null&&(s in a?a[s]=null:a.hasAttribute(s)&&a.removeAttribute(s)),a.addEventListener(l,n,t);break a}s in a?a[s]=n:n===!0?a.setAttribute(s,""):Tt(a,s,n)}}}function ya(a,l,s){switch(l){case"div":case"span":case"svg":case"path":case"a":case"g":case"p":case"li":break;case"img":_("error",a),_("load",a);var n=!1,t=!1,e;for(e in s)if(s.hasOwnProperty(e)){var i=s[e];if(i!=null)switch(e){case"src":n=!0;break;case"srcSet":t=!0;break;case"children":case"dangerouslySetInnerHTML":throw Error(f(137,l));default:K(a,l,e,i,s,null)}}t&&K(a,l,"srcSet",s.srcSet,s,null),n&&K(a,l,"src",s.src,s,null);return;case"input":_("invalid",a);var c=e=i=t=null,u=null,r=null;for(n in s)if(s.hasOwnProperty(n)){var g=s[n];if(g!=null)switch(n){case"name":t=g;break;case"type":i=g;break;case"checked":u=g;break;case"defaultChecked":r=g;break;case"value":e=g;break;case"defaultValue":c=g;break;case"children":case"dangerouslySetInnerHTML":if(g!=null)throw Error(f(137,l));break;default:K(a,l,n,g,s,null)}}Ou(a,e,c,u,r,i,t,!1);return;case"select":_("invalid",a),n=i=e=null;for(t in s)if(s.hasOwnProperty(t)&&(c=s[t],c!=null))switch(t){case"value":e=c;break;case"defaultValue":i=c;break;case"multiple":n=c;default:K(a,l,t,c,s,null)}l=e,s=i,a.multiple=!!n,l!=null?Gs(a,!!n,l,!1):s!=null&&Gs(a,!!n,s,!0);return;case"textarea":_("invalid",a),e=t=n=null;for(i in s)if(s.hasOwnProperty(i)&&(c=s[i],c!=null))switch(i){case"value":n=c;break;case"defaultValue":t=c;break;case"children":e=c;break;case"dangerouslySetInnerHTML":if(c!=null)throw Error(f(91));break;default:K(a,l,i,c,s,null)}Bu(a,n,t,e);return;case"option":for(u in s)if(s.hasOwnProperty(u)&&(n=s[u],n!=null))switch(u){case"selected":a.selected=n&&typeof n!="function"&&typeof n!="symbol";break;default:K(a,l,u,n,s,null)}return;case"dialog":_("beforetoggle",a),_("toggle",a),_("cancel",a),_("close",a);break;case"iframe":case"object":_("load",a);break;case"video":case"audio":for(n=0;n<et.length;n++)_(et[n],a);break;case"image":_("error",a),_("load",a);break;case"details":_("toggle",a);break;case"embed":case"source":case"link":_("error",a),_("load",a);case"area":case"base":case"br":case"col":case"hr":case"keygen":case"meta":case"param":case"track":case"wbr":case"menuitem":for(r in s)if(s.hasOwnProperty(r)&&(n=s[r],n!=null))switch(r){case"children":case"dangerouslySetInnerHTML":throw Error(f(137,l));default:K(a,l,r,n,s,null)}return;default:if(ai(l)){for(g in s)s.hasOwnProperty(g)&&(n=s[g],n!==void 0&&Gc(a,l,g,n,s,void 0));return}}for(c in s)s.hasOwnProperty(c)&&(n=s[c],n!=null&&K(a,l,c,n,s,null))}function yp(a,l,s,n){switch(l){case"div":case"span":case"svg":case"path":case"a":case"g":case"p":case"li":break;case"input":var t=null,e=null,i=null,c=null,u=null,r=null,g=null;for(m in s){var y=s[m];if(s.hasOwnProperty(m)&&y!=null)switch(m){case"checked":break;case"value":break;case"defaultValue":u=y;default:n.hasOwnProperty(m)||K(a,l,m,null,n,y)}}for(var p in n){var m=n[p];if(y=s[p],n.hasOwnProperty(p)&&(m!=null||y!=null))switch(p){case"type":e=m;break;case"name":t=m;break;case"checked":r=m;break;case"defaultChecked":g=m;break;case"value":i=m;break;case"defaultValue":c=m;break;case"children":case"dangerouslySetInnerHTML":if(m!=null)throw Error(f(137,l));break;default:m!==y&&K(a,l,p,m,n,y)}}Ie(a,i,c,u,r,g,e,t);return;case"select":m=i=c=p=null;for(e in s)if(u=s[e],s.hasOwnProperty(e)&&u!=null)switch(e){case"value":break;case"multiple":m=u;default:n.hasOwnProperty(e)||K(a,l,e,null,n,u)}for(t in n)if(e=n[t],u=s[t],n.hasOwnProperty(t)&&(e!=null||u!=null))switch(t){case"value":p=e;break;case"defaultValue":c=e;break;case"multiple":i=e;default:e!==u&&K(a,l,t,e,n,u)}l=c,s=i,n=m,p!=null?Gs(a,!!s,p,!1):!!n!=!!s&&(l!=null?Gs(a,!!s,l,!0):Gs(a,!!s,s?[]:"",!1));return;case"textarea":m=p=null;for(c in s)if(t=s[c],s.hasOwnProperty(c)&&t!=null&&!n.hasOwnProperty(c))switch(c){case"value":break;case"children":break;default:K(a,l,c,null,n,t)}for(i in n)if(t=n[i],e=s[i],n.hasOwnProperty(i)&&(t!=null||e!=null))switch(i){case"value":p=t;break;case"defaultValue":m=t;break;case"children":break;case"dangerouslySetInnerHTML":if(t!=null)throw Error(f(91));break;default:t!==e&&K(a,l,i,t,n,e)}Du(a,p,m);return;case"option":for(var z in s)if(p=s[z],s.hasOwnProperty(z)&&p!=null&&!n.hasOwnProperty(z))switch(z){case"selected":a.selected=!1;break;default:K(a,l,z,null,n,p)}for(u in n)if(p=n[u],m=s[u],n.hasOwnProperty(u)&&p!==m&&(p!=null||m!=null))switch(u){case"selected":a.selected=p&&typeof p!="function"&&typeof p!="symbol";break;default:K(a,l,u,p,n,m)}return;case"img":case"link":case"area":case"base":case"br":case"col":case"embed":case"hr":case"keygen":case"meta":case"param":case"source":case"track":case"wbr":case"menuitem":for(var T in s)p=s[T],s.hasOwnProperty(T)&&p!=null&&!n.hasOwnProperty(T)&&K(a,l,T,null,n,p);for(r in n)if(p=n[r],m=s[r],n.hasOwnProperty(r)&&p!==m&&(p!=null||m!=null))switch(r){case"children":case"dangerouslySetInnerHTML":if(p!=null)throw Error(f(137,l));break;default:K(a,l,r,p,n,m)}return;default:if(ai(l)){for(var J in s)p=s[J],s.hasOwnProperty(J)&&p!==void 0&&!n.hasOwnProperty(J)&&Gc(a,l,J,void 0,n,p);for(g in n)p=n[g],m=s[g],!n.hasOwnProperty(g)||p===m||p===void 0&&m===void 0||Gc(a,l,g,p,n,m);return}}for(var o in s)p=s[o],s.hasOwnProperty(o)&&p!=null&&!n.hasOwnProperty(o)&&K(a,l,o,null,n,p);for(y in n)p=n[y],m=s[y],!n.hasOwnProperty(y)||p===m||p==null&&m==null||K(a,l,y,p,n,m)}function Hv(a){switch(a){case"css":case"script":case"font":case"img":case"image":case"input":case"link":return!0;default:return!1}}function Sp(){if(typeof performance.getEntriesByType=="function"){for(var a=0,l=0,s=performance.getEntriesByType("resource"),n=0;n<s.length;n++){var t=s[n],e=t.transferSize,i=t.initiatorType,c=t.duration;if(e&&c&&Hv(i)){for(i=0,c=t.responseEnd,n+=1;n<s.length;n++){var u=s[n],r=u.startTime;if(r>c)break;var g=u.transferSize,y=u.initiatorType;g&&Hv(y)&&(u=u.responseEnd,i+=g*(u<c?1:(c-r)/(u-r)))}if(--n,l+=8*(e+i)/(t.duration/1e3),a++,10<a)break}}if(0<a)return l/a/1e6}return navigator.connection&&(a=navigator.connection.downlink,typeof a=="number")?a:5}var Yc=null,Zc=null;function Ae(a){return a.nodeType===9?a:a.ownerDocument}function _v(a){switch(a){case"http://www.w3.org/2000/svg":return 1;case"http://www.w3.org/1998/Math/MathML":return 2;default:return 0}}function Nv(a,l){if(a===0)switch(l){case"svg":return 1;case"math":return 2;default:return 0}return a===1&&l==="foreignObject"?0:a}function Lc(a,l){return a==="textarea"||a==="noscript"||typeof l.children=="string"||typeof l.children=="number"||typeof l.children=="bigint"||typeof l.dangerouslySetInnerHTML=="object"&&l.dangerouslySetInnerHTML!==null&&l.dangerouslySetInnerHTML.__html!=null}var Qc=null;function xp(){var a=window.event;return a&&a.type==="popstate"?a===Qc?!1:(Qc=a,!0):(Qc=null,!1)}var Rv=typeof setTimeout=="function"?setTimeout:void 0,zp=typeof clearTimeout=="function"?clearTimeout:void 0,jv=typeof Promise=="function"?Promise:void 0,Ap=typeof queueMicrotask=="function"?queueMicrotask:typeof jv<"u"?function(a){return jv.resolve(null).then(a).catch(wp)}:Rv;function wp(a){setTimeout(function(){throw a})}function ss(a){return a==="head"}function qv(a,l){var s=l,n=0;do{var t=s.nextSibling;if(a.removeChild(s),t&&t.nodeType===8)if(s=t.data,s==="/$"||s==="/&"){if(n===0){a.removeChild(t),yn(l);return}n--}else if(s==="$"||s==="$?"||s==="$~"||s==="$!"||s==="&")n++;else if(s==="html")ct(a.ownerDocument.documentElement);else if(s==="head"){s=a.ownerDocument.head,ct(s);for(var e=s.firstChild;e;){var i=e.nextSibling,c=e.nodeName;e[Tn]||c==="SCRIPT"||c==="STYLE"||c==="LINK"&&e.rel.toLowerCase()==="stylesheet"||s.removeChild(e),e=i}}else s==="body"&&ct(a.ownerDocument.body);s=t}while(s);yn(l)}function Gv(a,l){var s=a;a=0;do{var n=s.nextSibling;if(s.nodeType===1?l?(s._stashedDisplay=s.style.display,s.style.display="none"):(s.style.display=s._stashedDisplay||"",s.getAttribute("style")===""&&s.removeAttribute("style")):s.nodeType===3&&(l?(s._stashedText=s.nodeValue,s.nodeValue=""):s.nodeValue=s._stashedText||""),n&&n.nodeType===8)if(s=n.data,s==="/$"){if(a===0)break;a--}else s!=="$"&&s!=="$?"&&s!=="$~"&&s!=="$!"||a++;s=n}while(s)}function Xc(a){var l=a.firstChild;for(l&&l.nodeType===10&&(l=l.nextSibling);l;){var s=l;switch(l=l.nextSibling,s.nodeName){case"HTML":case"HEAD":case"BODY":Xc(s),Fe(s);continue;case"SCRIPT":case"STYLE":continue;case"LINK":if(s.rel.toLowerCase()==="stylesheet")continue}a.removeChild(s)}}function Tp(a,l,s,n){for(;a.nodeType===1;){var t=s;if(a.nodeName.toLowerCase()!==l.toLowerCase()){if(!n&&(a.nodeName!=="INPUT"||a.type!=="hidden"))break}else if(n){if(!a[Tn])switch(l){case"meta":if(!a.hasAttribute("itemprop"))break;return a;case"link":if(e=a.getAttribute("rel"),e==="stylesheet"&&a.hasAttribute("data-precedence"))break;if(e!==t.rel||a.getAttribute("href")!==(t.href==null||t.href===""?null:t.href)||a.getAttribute("crossorigin")!==(t.crossOrigin==null?null:t.crossOrigin)||a.getAttribute("title")!==(t.title==null?null:t.title))break;return a;case"style":if(a.hasAttribute("data-precedence"))break;return a;case"script":if(e=a.getAttribute("src"),(e!==(t.src==null?null:t.src)||a.getAttribute("type")!==(t.type==null?null:t.type)||a.getAttribute("crossorigin")!==(t.crossOrigin==null?null:t.crossOrigin))&&e&&a.hasAttribute("async")&&!a.hasAttribute("itemprop"))break;return a;default:return a}}else if(l==="input"&&a.type==="hidden"){var e=t.name==null?null:""+t.name;if(t.type==="hidden"&&a.getAttribute("name")===e)return a}else return a;if(a=Pa(a.nextSibling),a===null)break}return null}function Mp(a,l,s){if(l==="")return null;for(;a.nodeType!==3;)if((a.nodeType!==1||a.nodeName!=="INPUT"||a.type!=="hidden")&&!s||(a=Pa(a.nextSibling),a===null))return null;return a}function Yv(a,l){for(;a.nodeType!==8;)if((a.nodeType!==1||a.nodeName!=="INPUT"||a.type!=="hidden")&&!l||(a=Pa(a.nextSibling),a===null))return null;return a}function Vc(a){return a.data==="$?"||a.data==="$~"}function Kc(a){return a.data==="$!"||a.data==="$?"&&a.ownerDocument.readyState!=="loading"}function Ep(a,l){var s=a.ownerDocument;if(a.data==="$~")a._reactRetry=l;else if(a.data!=="$?"||s.readyState!=="loading")l();else{var n=function(){l(),s.removeEventListener("DOMContentLoaded",n)};s.addEventListener("DOMContentLoaded",n),a._reactRetry=n}}function Pa(a){for(;a!=null;a=a.nextSibling){var l=a.nodeType;if(l===1||l===3)break;if(l===8){if(l=a.data,l==="$"||l==="$!"||l==="$?"||l==="$~"||l==="&"||l==="F!"||l==="F")break;if(l==="/$"||l==="/&")return null}}return a}var Jc=null;function Zv(a){a=a.nextSibling;for(var l=0;a;){if(a.nodeType===8){var s=a.data;if(s==="/$"||s==="/&"){if(l===0)return Pa(a.nextSibling);l--}else s!=="$"&&s!=="$!"&&s!=="$?"&&s!=="$~"&&s!=="&"||l++}a=a.nextSibling}return null}function Lv(a){a=a.previousSibling;for(var l=0;a;){if(a.nodeType===8){var s=a.data;if(s==="$"||s==="$!"||s==="$?"||s==="$~"||s==="&"){if(l===0)return a;l--}else s!=="/$"&&s!=="/&"||l++}a=a.previousSibling}return null}function Qv(a,l,s){switch(l=Ae(s),a){case"html":if(a=l.documentElement,!a)throw Error(f(452));return a;case"head":if(a=l.head,!a)throw Error(f(453));return a;case"body":if(a=l.body,!a)throw Error(f(454));return a;default:throw Error(f(451))}}function ct(a){for(var l=a.attributes;l.length;)a.removeAttributeNode(l[0]);Fe(a)}var al=new Map,Xv=new Set;function we(a){return typeof a.getRootNode=="function"?a.getRootNode():a.nodeType===9?a:a.ownerDocument}var Cl=x.d;x.d={f:Op,r:Dp,D:Bp,C:Up,L:kp,m:Cp,X:_p,S:Hp,M:Np};function Op(){var a=Cl.f(),l=me();return a||l}function Dp(a){var l=Rs(a);l!==null&&l.tag===5&&l.type==="form"?co(l):Cl.r(a)}var gn=typeof document>"u"?null:document;function Vv(a,l,s){var n=gn;if(n&&typeof l=="string"&&l){var t=Va(l);t='link[rel="'+a+'"][href="'+t+'"]',typeof s=="string"&&(t+='[crossorigin="'+s+'"]'),Xv.has(t)||(Xv.add(t),a={rel:a,crossOrigin:s,href:l},n.querySelector(t)===null&&(l=n.createElement("link"),ya(l,"link",a),fa(l),n.head.appendChild(l)))}}function Bp(a){Cl.D(a),Vv("dns-prefetch",a,null)}function Up(a,l){Cl.C(a,l),Vv("preconnect",a,l)}function kp(a,l,s){Cl.L(a,l,s);var n=gn;if(n&&a&&l){var t='link[rel="preload"][as="'+Va(l)+'"]';l==="image"&&s&&s.imageSrcSet?(t+='[imagesrcset="'+Va(s.imageSrcSet)+'"]',typeof s.imageSizes=="string"&&(t+='[imagesizes="'+Va(s.imageSizes)+'"]')):t+='[href="'+Va(a)+'"]';var e=t;switch(l){case"style":e=bn(a);break;case"script":e=hn(a)}al.has(e)||(a=k({rel:"preload",href:l==="image"&&s&&s.imageSrcSet?void 0:a,as:l},s),al.set(e,a),n.querySelector(t)!==null||l==="style"&&n.querySelector(ut(e))||l==="script"&&n.querySelector(dt(e))||(l=n.createElement("link"),ya(l,"link",a),fa(l),n.head.appendChild(l)))}}function Cp(a,l){Cl.m(a,l);var s=gn;if(s&&a){var n=l&&typeof l.as=="string"?l.as:"script",t='link[rel="modulepreload"][as="'+Va(n)+'"][href="'+Va(a)+'"]',e=t;switch(n){case"audioworklet":case"paintworklet":case"serviceworker":case"sharedworker":case"worker":case"script":e=hn(a)}if(!al.has(e)&&(a=k({rel:"modulepreload",href:a},l),al.set(e,a),s.querySelector(t)===null)){switch(n){case"audioworklet":case"paintworklet":case"serviceworker":case"sharedworker":case"worker":case"script":if(s.querySelector(dt(e)))return}n=s.createElement("link"),ya(n,"link",a),fa(n),s.head.appendChild(n)}}}function Hp(a,l,s){Cl.S(a,l,s);var n=gn;if(n&&a){var t=js(n).hoistableStyles,e=bn(a);l=l||"default";var i=t.get(e);if(!i){var c={loading:0,preload:null};if(i=n.querySelector(ut(e)))c.loading=5;else{a=k({rel:"stylesheet",href:a,"data-precedence":l},s),(s=al.get(e))&&Wc(a,s);var u=i=n.createElement("link");fa(u),ya(u,"link",a),u._p=new Promise(function(r,g){u.onload=r,u.onerror=g}),u.addEventListener("load",function(){c.loading|=1}),u.addEventListener("error",function(){c.loading|=2}),c.loading|=4,Te(i,l,n)}i={type:"stylesheet",instance:i,count:1,state:c},t.set(e,i)}}}function _p(a,l){Cl.X(a,l);var s=gn;if(s&&a){var n=js(s).hoistableScripts,t=hn(a),e=n.get(t);e||(e=s.querySelector(dt(t)),e||(a=k({src:a,async:!0},l),(l=al.get(t))&&Fc(a,l),e=s.createElement("script"),fa(e),ya(e,"link",a),s.head.appendChild(e)),e={type:"script",instance:e,count:1,state:null},n.set(t,e))}}function Np(a,l){Cl.M(a,l);var s=gn;if(s&&a){var n=js(s).hoistableScripts,t=hn(a),e=n.get(t);e||(e=s.querySelector(dt(t)),e||(a=k({src:a,async:!0,type:"module"},l),(l=al.get(t))&&Fc(a,l),e=s.createElement("script"),fa(e),ya(e,"link",a),s.head.appendChild(e)),e={type:"script",instance:e,count:1,state:null},n.set(t,e))}}function Kv(a,l,s,n){var t=(t=Nl.current)?we(t):null;if(!t)throw Error(f(446));switch(a){case"meta":case"title":return null;case"style":return typeof s.precedence=="string"&&typeof s.href=="string"?(l=bn(s.href),s=js(t).hoistableStyles,n=s.get(l),n||(n={type:"style",instance:null,count:0,state:null},s.set(l,n)),n):{type:"void",instance:null,count:0,state:null};case"link":if(s.rel==="stylesheet"&&typeof s.href=="string"&&typeof s.precedence=="string"){a=bn(s.href);var e=js(t).hoistableStyles,i=e.get(a);if(i||(t=t.ownerDocument||t,i={type:"stylesheet",instance:null,count:0,state:{loading:0,preload:null}},e.set(a,i),(e=t.querySelector(ut(a)))&&!e._p&&(i.instance=e,i.state.loading=5),al.has(a)||(s={rel:"preload",as:"style",href:s.href,crossOrigin:s.crossOrigin,integrity:s.integrity,media:s.media,hrefLang:s.hrefLang,referrerPolicy:s.referrerPolicy},al.set(a,s),e||Rp(t,a,s,i.state))),l&&n===null)throw Error(f(528,""));return i}if(l&&n!==null)throw Error(f(529,""));return null;case"script":return l=s.async,s=s.src,typeof s=="string"&&l&&typeof l!="function"&&typeof l!="symbol"?(l=hn(s),s=js(t).hoistableScripts,n=s.get(l),n||(n={type:"script",instance:null,count:0,state:null},s.set(l,n)),n):{type:"void",instance:null,count:0,state:null};default:throw Error(f(444,a))}}function bn(a){return'href="'+Va(a)+'"'}function ut(a){return'link[rel="stylesheet"]['+a+"]"}function Jv(a){return k({},a,{"data-precedence":a.precedence,precedence:null})}function Rp(a,l,s,n){a.querySelector('link[rel="preload"][as="style"]['+l+"]")?n.loading=1:(l=a.createElement("link"),n.preload=l,l.addEventListener("load",function(){return n.loading|=1}),l.addEventListener("error",function(){return n.loading|=2}),ya(l,"link",s),fa(l),a.head.appendChild(l))}function hn(a){return'[src="'+Va(a)+'"]'}function dt(a){return"script[async]"+a}function Wv(a,l,s){if(l.count++,l.instance===null)switch(l.type){case"style":var n=a.querySelector('style[data-href~="'+Va(s.href)+'"]');if(n)return l.instance=n,fa(n),n;var t=k({},s,{"data-href":s.href,"data-precedence":s.precedence,href:null,precedence:null});return n=(a.ownerDocument||a).createElement("style"),fa(n),ya(n,"style",t),Te(n,s.precedence,a),l.instance=n;case"stylesheet":t=bn(s.href);var e=a.querySelector(ut(t));if(e)return l.state.loading|=4,l.instance=e,fa(e),e;n=Jv(s),(t=al.get(t))&&Wc(n,t),e=(a.ownerDocument||a).createElement("link"),fa(e);var i=e;return i._p=new Promise(function(c,u){i.onload=c,i.onerror=u}),ya(e,"link",n),l.state.loading|=4,Te(e,s.precedence,a),l.instance=e;case"script":return e=hn(s.src),(t=a.querySelector(dt(e)))?(l.instance=t,fa(t),t):(n=s,(t=al.get(e))&&(n=k({},s),Fc(n,t)),a=a.ownerDocument||a,t=a.createElement("script"),fa(t),ya(t,"link",n),a.head.appendChild(t),l.instance=t);case"void":return null;default:throw Error(f(443,l.type))}else l.type==="stylesheet"&&(l.state.loading&4)===0&&(n=l.instance,l.state.loading|=4,Te(n,s.precedence,a));return l.instance}function Te(a,l,s){for(var n=s.querySelectorAll('link[rel="stylesheet"][data-precedence],style[data-precedence]'),t=n.length?n[n.length-1]:null,e=t,i=0;i<n.length;i++){var c=n[i];if(c.dataset.precedence===l)e=c;else if(e!==t)break}e?e.parentNode.insertBefore(a,e.nextSibling):(l=s.nodeType===9?s.head:s,l.insertBefore(a,l.firstChild))}function Wc(a,l){a.crossOrigin==null&&(a.crossOrigin=l.crossOrigin),a.referrerPolicy==null&&(a.referrerPolicy=l.referrerPolicy),a.title==null&&(a.title=l.title)}function Fc(a,l){a.crossOrigin==null&&(a.crossOrigin=l.crossOrigin),a.referrerPolicy==null&&(a.referrerPolicy=l.referrerPolicy),a.integrity==null&&(a.integrity=l.integrity)}var Me=null;function Fv(a,l,s){if(Me===null){var n=new Map,t=Me=new Map;t.set(s,n)}else t=Me,n=t.get(s),n||(n=new Map,t.set(s,n));if(n.has(a))return n;for(n.set(a,null),s=s.getElementsByTagName(a),t=0;t<s.length;t++){var e=s[t];if(!(e[Tn]||e[ma]||a==="link"&&e.getAttribute("rel")==="stylesheet")&&e.namespaceURI!=="http://www.w3.org/2000/svg"){var i=e.getAttribute(l)||"";i=a+i;var c=n.get(i);c?c.push(e):n.set(i,[e])}}return n}function $v(a,l,s){a=a.ownerDocument||a,a.head.insertBefore(s,l==="title"?a.querySelector("head > title"):null)}function jp(a,l,s){if(s===1||l.itemProp!=null)return!1;switch(a){case"meta":case"title":return!0;case"style":if(typeof l.precedence!="string"||typeof l.href!="string"||l.href==="")break;return!0;case"link":if(typeof l.rel!="string"||typeof l.href!="string"||l.href===""||l.onLoad||l.onError)break;switch(l.rel){case"stylesheet":return a=l.disabled,typeof l.precedence=="string"&&a==null;default:return!0}case"script":if(l.async&&typeof l.async!="function"&&typeof l.async!="symbol"&&!l.onLoad&&!l.onError&&l.src&&typeof l.src=="string")return!0}return!1}function Iv(a){return!(a.type==="stylesheet"&&(a.state.loading&3)===0)}function qp(a,l,s,n){if(s.type==="stylesheet"&&(typeof n.media!="string"||matchMedia(n.media).matches!==!1)&&(s.state.loading&4)===0){if(s.instance===null){var t=bn(n.href),e=l.querySelector(ut(t));if(e){l=e._p,l!==null&&typeof l=="object"&&typeof l.then=="function"&&(a.count++,a=Ee.bind(a),l.then(a,a)),s.state.loading|=4,s.instance=e,fa(e);return}e=l.ownerDocument||l,n=Jv(n),(t=al.get(t))&&Wc(n,t),e=e.createElement("link"),fa(e);var i=e;i._p=new Promise(function(c,u){i.onload=c,i.onerror=u}),ya(e,"link",n),s.instance=e}a.stylesheets===null&&(a.stylesheets=new Map),a.stylesheets.set(s,l),(l=s.state.preload)&&(s.state.loading&3)===0&&(a.count++,s=Ee.bind(a),l.addEventListener("load",s),l.addEventListener("error",s))}}var $c=0;function Gp(a,l){return a.stylesheets&&a.count===0&&De(a,a.stylesheets),0<a.count||0<a.imgCount?function(s){var n=setTimeout(function(){if(a.stylesheets&&De(a,a.stylesheets),a.unsuspend){var e=a.unsuspend;a.unsuspend=null,e()}},6e4+l);0<a.imgBytes&&$c===0&&($c=62500*Sp());var t=setTimeout(function(){if(a.waitingForImages=!1,a.count===0&&(a.stylesheets&&De(a,a.stylesheets),a.unsuspend)){var e=a.unsuspend;a.unsuspend=null,e()}},(a.imgBytes>$c?50:800)+l);return a.unsuspend=s,function(){a.unsuspend=null,clearTimeout(n),clearTimeout(t)}}:null}function Ee(){if(this.count--,this.count===0&&(this.imgCount===0||!this.waitingForImages)){if(this.stylesheets)De(this,this.stylesheets);else if(this.unsuspend){var a=this.unsuspend;this.unsuspend=null,a()}}}var Oe=null;function De(a,l){a.stylesheets=null,a.unsuspend!==null&&(a.count++,Oe=new Map,l.forEach(Yp,a),Oe=null,Ee.call(a))}function Yp(a,l){if(!(l.state.loading&4)){var s=Oe.get(a);if(s)var n=s.get(null);else{s=new Map,Oe.set(a,s);for(var t=a.querySelectorAll("link[data-precedence],style[data-precedence]"),e=0;e<t.length;e++){var i=t[e];(i.nodeName==="LINK"||i.getAttribute("media")!=="not all")&&(s.set(i.dataset.precedence,i),n=i)}n&&s.set(null,n)}t=l.instance,i=t.getAttribute("data-precedence"),e=s.get(i)||n,e===n&&s.set(null,t),s.set(i,t),this.count++,n=Ee.bind(this),t.addEventListener("load",n),t.addEventListener("error",n),e?e.parentNode.insertBefore(t,e.nextSibling):(a=a.nodeType===9?a.head:a,a.insertBefore(t,a.firstChild)),l.state.loading|=4}}var ot={$$typeof:La,Provider:null,Consumer:null,_currentValue:M,_currentValue2:M,_threadCount:0};function Zp(a,l,s,n,t,e,i,c,u){this.tag=1,this.containerInfo=a,this.pingCache=this.current=this.pendingChildren=null,this.timeoutHandle=-1,this.callbackNode=this.next=this.pendingContext=this.context=this.cancelPendingCommit=null,this.callbackPriority=0,this.expirationTimes=Ve(-1),this.entangledLanes=this.shellSuspendCounter=this.errorRecoveryDisabledLanes=this.expiredLanes=this.warmLanes=this.pingedLanes=this.suspendedLanes=this.pendingLanes=0,this.entanglements=Ve(0),this.hiddenUpdates=Ve(null),this.identifierPrefix=n,this.onUncaughtError=t,this.onCaughtError=e,this.onRecoverableError=i,this.pooledCache=null,this.pooledCacheLanes=0,this.formState=u,this.incompleteTransitions=new Map}function Pv(a,l,s,n,t,e,i,c,u,r,g,y){return a=new Zp(a,l,s,i,u,r,g,y,c),l=1,e===!0&&(l|=24),e=_a(3,null,null,l),a.current=e,e.stateNode=a,l=Bi(),l.refCount++,a.pooledCache=l,l.refCount++,e.memoizedState={element:n,isDehydrated:s,cache:l},Hi(e),a}function ar(a){return a?(a=Js,a):Js}function lr(a,l,s,n,t,e){t=ar(t),n.context===null?n.context=t:n.pendingContext=t,n=Xl(l),n.payload={element:s},e=e===void 0?null:e,e!==null&&(n.callback=e),s=Vl(a,n,l),s!==null&&(Ba(s,a,l),Zn(s,a,l))}function sr(a,l){if(a=a.memoizedState,a!==null&&a.dehydrated!==null){var s=a.retryLane;a.retryLane=s!==0&&s<l?s:l}}function Ic(a,l){sr(a,l),(a=a.alternate)&&sr(a,l)}function nr(a){if(a.tag===13||a.tag===31){var l=gs(a,67108864);l!==null&&Ba(l,a,67108864),Ic(a,67108864)}}function tr(a){if(a.tag===13||a.tag===31){var l=Ga();l=Ke(l);var s=gs(a,l);s!==null&&Ba(s,a,l),Ic(a,l)}}var Be=!0;function Lp(a,l,s,n){var t=h.T;h.T=null;var e=x.p;try{x.p=2,Pc(a,l,s,n)}finally{x.p=e,h.T=t}}function Qp(a,l,s,n){var t=h.T;h.T=null;var e=x.p;try{x.p=8,Pc(a,l,s,n)}finally{x.p=e,h.T=t}}function Pc(a,l,s,n){if(Be){var t=au(n);if(t===null)qc(a,l,n,Ue,s),ir(a,n);else if(Vp(t,a,l,s,n))n.stopPropagation();else if(ir(a,n),l&4&&-1<Xp.indexOf(a)){for(;t!==null;){var e=Rs(t);if(e!==null)switch(e.tag){case 3:if(e=e.stateNode,e.current.memoizedState.isDehydrated){var i=vs(e.pendingLanes);if(i!==0){var c=e;for(c.pendingLanes|=2,c.entangledLanes|=2;i;){var u=1<<31-Ca(i);c.entanglements[1]|=u,i&=~u}rl(e),(Z&6)===0&&(fe=Ua()+500,tt(0))}}break;case 31:case 13:c=gs(e,2),c!==null&&Ba(c,e,2),me(),Ic(e,2)}if(e=au(n),e===null&&qc(a,l,n,Ue,s),e===t)break;t=e}t!==null&&n.stopPropagation()}else qc(a,l,n,null,s)}}function au(a){return a=si(a),lu(a)}var Ue=null;function lu(a){if(Ue=null,a=Ns(a),a!==null){var l=C(a);if(l===null)a=null;else{var s=l.tag;if(s===13){if(a=Sa(l),a!==null)return a;a=null}else if(s===31){if(a=il(l),a!==null)return a;a=null}else if(s===3){if(l.stateNode.current.memoizedState.isDehydrated)return l.tag===3?l.stateNode.containerInfo:null;a=null}else l!==a&&(a=null)}}return Ue=a,null}function er(a){switch(a){case"beforetoggle":case"cancel":case"click":case"close":case"contextmenu":case"copy":case"cut":case"auxclick":case"dblclick":case"dragend":case"dragstart":case"drop":case"focusin":case"focusout":case"input":case"invalid":case"keydown":case"keypress":case"keyup":case"mousedown":case"mouseup":case"paste":case"pause":case"play":case"pointercancel":case"pointerdown":case"pointerup":case"ratechange":case"reset":case"resize":case"seeked":case"submit":case"toggle":case"touchcancel":case"touchend":case"touchstart":case"volumechange":case"change":case"selectionchange":case"textInput":case"compositionstart":case"compositionend":case"compositionupdate":case"beforeblur":case"afterblur":case"beforeinput":case"blur":case"fullscreenchange":case"focus":case"hashchange":case"popstate":case"select":case"selectstart":return 2;case"drag":case"dragenter":case"dragexit":case"dragleave":case"dragover":case"mousemove":case"mouseout":case"mouseover":case"pointermove":case"pointerout":case"pointerover":case"scroll":case"touchmove":case"wheel":case"mouseenter":case"mouseleave":case"pointerenter":case"pointerleave":return 8;case"message":switch(Dr()){case ru:return 2;case fu:return 8;case St:case Br:return 32;case pu:return 268435456;default:return 32}default:return 32}}var su=!1,ns=null,ts=null,es=null,vt=new Map,rt=new Map,is=[],Xp="mousedown mouseup touchcancel touchend touchstart auxclick dblclick pointercancel pointerdown pointerup dragend dragstart drop compositionend compositionstart keydown keypress keyup input textInput copy cut paste click change contextmenu reset".split(" ");function ir(a,l){switch(a){case"focusin":case"focusout":ns=null;break;case"dragenter":case"dragleave":ts=null;break;case"mouseover":case"mouseout":es=null;break;case"pointerover":case"pointerout":vt.delete(l.pointerId);break;case"gotpointercapture":case"lostpointercapture":rt.delete(l.pointerId)}}function ft(a,l,s,n,t,e){return a===null||a.nativeEvent!==e?(a={blockedOn:l,domEventName:s,eventSystemFlags:n,nativeEvent:e,targetContainers:[t]},l!==null&&(l=Rs(l),l!==null&&nr(l)),a):(a.eventSystemFlags|=n,l=a.targetContainers,t!==null&&l.indexOf(t)===-1&&l.push(t),a)}function Vp(a,l,s,n,t){switch(l){case"focusin":return ns=ft(ns,a,l,s,n,t),!0;case"dragenter":return ts=ft(ts,a,l,s,n,t),!0;case"mouseover":return es=ft(es,a,l,s,n,t),!0;case"pointerover":var e=t.pointerId;return vt.set(e,ft(vt.get(e)||null,a,l,s,n,t)),!0;case"gotpointercapture":return e=t.pointerId,rt.set(e,ft(rt.get(e)||null,a,l,s,n,t)),!0}return!1}function cr(a){var l=Ns(a.target);if(l!==null){var s=C(l);if(s!==null){if(l=s.tag,l===13){if(l=Sa(s),l!==null){a.blockedOn=l,Su(a.priority,function(){tr(s)});return}}else if(l===31){if(l=il(s),l!==null){a.blockedOn=l,Su(a.priority,function(){tr(s)});return}}else if(l===3&&s.stateNode.current.memoizedState.isDehydrated){a.blockedOn=s.tag===3?s.stateNode.containerInfo:null;return}}}a.blockedOn=null}function ke(a){if(a.blockedOn!==null)return!1;for(var l=a.targetContainers;0<l.length;){var s=au(a.nativeEvent);if(s===null){s=a.nativeEvent;var n=new s.constructor(s.type,s);li=n,s.target.dispatchEvent(n),li=null}else return l=Rs(s),l!==null&&nr(l),a.blockedOn=s,!1;l.shift()}return!0}function ur(a,l,s){ke(a)&&s.delete(l)}function Kp(){su=!1,ns!==null&&ke(ns)&&(ns=null),ts!==null&&ke(ts)&&(ts=null),es!==null&&ke(es)&&(es=null),vt.forEach(ur),rt.forEach(ur)}function Ce(a,l){a.blockedOn===l&&(a.blockedOn=null,su||(su=!0,S.unstable_scheduleCallback(S.unstable_NormalPriority,Kp)))}var He=null;function dr(a){He!==a&&(He=a,S.unstable_scheduleCallback(S.unstable_NormalPriority,function(){He===a&&(He=null);for(var l=0;l<a.length;l+=3){var s=a[l],n=a[l+1],t=a[l+2];if(typeof n!="function"){if(lu(n||s)===null)continue;break}var e=Rs(s);e!==null&&(a.splice(l,3),l-=3,ac(e,{pending:!0,data:t,method:s.method,action:n},n,t))}}))}function yn(a){function l(u){return Ce(u,a)}ns!==null&&Ce(ns,a),ts!==null&&Ce(ts,a),es!==null&&Ce(es,a),vt.forEach(l),rt.forEach(l);for(var s=0;s<is.length;s++){var n=is[s];n.blockedOn===a&&(n.blockedOn=null)}for(;0<is.length&&(s=is[0],s.blockedOn===null);)cr(s),s.blockedOn===null&&is.shift();if(s=(a.ownerDocument||a).$$reactFormReplay,s!=null)for(n=0;n<s.length;n+=3){var t=s[n],e=s[n+1],i=t[wa]||null;if(typeof e=="function")i||dr(s);else if(i){var c=null;if(e&&e.hasAttribute("formAction")){if(t=e,i=e[wa]||null)c=i.formAction;else if(lu(t)!==null)continue}else c=i.action;typeof c=="function"?s[n+1]=c:(s.splice(n,3),n-=3),dr(s)}}}function or(){function a(e){e.canIntercept&&e.info==="react-transition"&&e.intercept({handler:function(){return new Promise(function(i){return t=i})},focusReset:"manual",scroll:"manual"})}function l(){t!==null&&(t(),t=null),n||setTimeout(s,20)}function s(){if(!n&&!navigation.transition){var e=navigation.currentEntry;e&&e.url!=null&&navigation.navigate(e.url,{state:e.getState(),info:"react-transition",history:"replace"})}}if(typeof navigation=="object"){var n=!1,t=null;return navigation.addEventListener("navigate",a),navigation.addEventListener("navigatesuccess",l),navigation.addEventListener("navigateerror",l),setTimeout(s,100),function(){n=!0,navigation.removeEventListener("navigate",a),navigation.removeEventListener("navigatesuccess",l),navigation.removeEventListener("navigateerror",l),t!==null&&(t(),t=null)}}}function nu(a){this._internalRoot=a}_e.prototype.render=nu.prototype.render=function(a){var l=this._internalRoot;if(l===null)throw Error(f(409));var s=l.current,n=Ga();lr(s,n,a,l,null,null)},_e.prototype.unmount=nu.prototype.unmount=function(){var a=this._internalRoot;if(a!==null){this._internalRoot=null;var l=a.containerInfo;lr(a.current,2,null,a,null,null),me(),l[_s]=null}};function _e(a){this._internalRoot=a}_e.prototype.unstable_scheduleHydration=function(a){if(a){var l=yu();a={blockedOn:null,target:a,priority:l};for(var s=0;s<is.length&&l!==0&&l<is[s].priority;s++);is.splice(s,0,a),s===0&&cr(a)}};var vr=D.version;if(vr!=="19.2.6")throw Error(f(527,vr,"19.2.6"));x.findDOMNode=function(a){var l=a._reactInternals;if(l===void 0)throw typeof a.render=="function"?Error(f(188)):(a=Object.keys(a).join(","),Error(f(268,a)));return a=Ya(l),a=a!==null?Ds(a):null,a=a===null?null:a.stateNode,a};var Jp={bundleType:0,version:"19.2.6",rendererPackageName:"react-dom",currentDispatcherRef:h,reconcilerVersion:"19.2.6"};if(typeof __REACT_DEVTOOLS_GLOBAL_HOOK__<"u"){var Ne=__REACT_DEVTOOLS_GLOBAL_HOOK__;if(!Ne.isDisabled&&Ne.supportsFiber)try{zn=Ne.inject(Jp),ka=Ne}catch{}}return pt.createRoot=function(a,l){if(!U(a))throw Error(f(299));var s=!1,n="",t=ho,e=yo,i=So;return l!=null&&(l.unstable_strictMode===!0&&(s=!0),l.identifierPrefix!==void 0&&(n=l.identifierPrefix),l.onUncaughtError!==void 0&&(t=l.onUncaughtError),l.onCaughtError!==void 0&&(e=l.onCaughtError),l.onRecoverableError!==void 0&&(i=l.onRecoverableError)),l=Pv(a,1,!1,null,null,s,n,null,t,e,i,or),a[_s]=l.current,jc(a),new nu(l)},pt.hydrateRoot=function(a,l,s){if(!U(a))throw Error(f(299));var n=!1,t="",e=ho,i=yo,c=So,u=null;return s!=null&&(s.unstable_strictMode===!0&&(n=!0),s.identifierPrefix!==void 0&&(t=s.identifierPrefix),s.onUncaughtError!==void 0&&(e=s.onUncaughtError),s.onCaughtError!==void 0&&(i=s.onCaughtError),s.onRecoverableError!==void 0&&(c=s.onRecoverableError),s.formState!==void 0&&(u=s.formState)),l=Pv(a,1,!0,l,s??null,n,t,u,e,i,c,or),l.context=ar(null),s=l.current,n=Ga(),n=Ke(n),t=Xl(n),t.callback=null,Vl(s,t,n),s=n,l.current.lanes=s,wn(l,s),rl(l),a[_s]=l.current,jc(a),new _e(l)},pt.version="19.2.6",pt}var mr;function tm(){if(mr)return tu.exports;mr=1;function S(){if(!(typeof __REACT_DEVTOOLS_GLOBAL_HOOK__>"u"||typeof __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE!="function"))try{__REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE(S)}catch(D){console.error(D)}}return S(),tu.exports=nm(),tu.exports}var em=tm();const im=$p(em);/**
 * @license lucide-react v0.577.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const yr=(...S)=>S.filter((D,N,f)=>!!D&&D.trim()!==""&&f.indexOf(D)===N).join(" ").trim();/**
 * @license lucide-react v0.577.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const cm=S=>S.replace(/([a-z0-9])([A-Z])/g,"$1-$2").toLowerCase();/**
 * @license lucide-react v0.577.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const um=S=>S.replace(/^([A-Z])|[\s-_]+(\w)/g,(D,N,f)=>f?f.toUpperCase():N.toLowerCase());/**
 * @license lucide-react v0.577.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const gr=S=>{const D=um(S);return D.charAt(0).toUpperCase()+D.slice(1)};/**
 * @license lucide-react v0.577.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */var dm={xmlns:"http://www.w3.org/2000/svg",width:24,height:24,viewBox:"0 0 24 24",fill:"none",stroke:"currentColor",strokeWidth:2,strokeLinecap:"round",strokeLinejoin:"round"};/**
 * @license lucide-react v0.577.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const om=S=>{for(const D in S)if(D.startsWith("aria-")||D==="role"||D==="title")return!0;return!1};/**
 * @license lucide-react v0.577.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const vm=fl.forwardRef(({color:S="currentColor",size:D=24,strokeWidth:N=2,absoluteStrokeWidth:f,className:U="",children:C,iconNode:Sa,...il},Aa)=>fl.createElement("svg",{ref:Aa,...dm,width:D,height:D,stroke:S,strokeWidth:f?Number(N)*24/Number(D):N,className:yr("lucide",U),...!C&&!om(il)&&{"aria-hidden":"true"},...il},[...Sa.map(([Ya,Ds])=>fl.createElement(Ya,Ds)),...Array.isArray(C)?C:[C]]));/**
 * @license lucide-react v0.577.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const us=(S,D)=>{const N=fl.forwardRef(({className:f,...U},C)=>fl.createElement(vm,{ref:C,iconNode:D,className:yr(`lucide-${cm(gr(S))}`,`lucide-${S}`,f),...U}));return N.displayName=gr(S),N};/**
 * @license lucide-react v0.577.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const rm=[["path",{d:"M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2",key:"169zse"}]],Sr=us("activity",rm);/**
 * @license lucide-react v0.577.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const fm=[["path",{d:"M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8",key:"5wwlr5"}],["path",{d:"M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",key:"r6nss1"}]],Re=us("house",fm);/**
 * @license lucide-react v0.577.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const pm=[["path",{d:"M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z",key:"zw3jo"}],["path",{d:"M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12",key:"1wduqc"}],["path",{d:"M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17",key:"kqbvx6"}]],je=us("layers",pm);/**
 * @license lucide-react v0.577.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const mm=[["path",{d:"M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z",key:"oel41y"}]],xr=us("shield",mm);/**
 * @license lucide-react v0.577.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const gm=[["path",{d:"M14 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z",key:"17jzev"}]],zr=us("thermometer",gm);/**
 * @license lucide-react v0.577.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const bm=[["path",{d:"m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3",key:"wmoenq"}],["path",{d:"M12 9v4",key:"juzpu7"}],["path",{d:"M12 17h.01",key:"p32p05"}]],Ar=us("triangle-alert",bm);/**
 * @license lucide-react v0.577.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const hm=[["path",{d:"M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2",key:"1yyitq"}],["path",{d:"M16 3.128a4 4 0 0 1 0 7.744",key:"16gr8j"}],["path",{d:"M22 21v-2a4 4 0 0 0-3-3.87",key:"kshegd"}],["circle",{cx:"9",cy:"7",r:"4",key:"nufk8"}]],wr=us("users",hm);/**
 * @license lucide-react v0.577.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const ym=[["path",{d:"M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z",key:"1xq2db"}]],Tr=us("zap",ym),cu=[{id:"home",label:"Home",icon:Re,section:"Overview"},{id:"house",label:"House",icon:Re,section:"Overview"},{id:"zones",label:"Zones",icon:je,chip:"5",section:"Overview"},{id:"rooms",label:"Rooms",icon:je,chip:"19",section:"Overview"},{id:"energy",label:"Energy",icon:Tr,section:"Systems"},{id:"hvac",label:"HVAC",icon:zr,section:"Systems"},{id:"presence",label:"Presence",icon:wr,chip:"3/4",section:"Systems"},{id:"security",label:"Security",icon:xr,section:"Systems"},{id:"safety",label:"Safety",icon:Ar,section:"Systems"},{id:"diagnostics",label:"Diagnostics",icon:Sr,section:"URA"}];function Sm({active:S,onChange:D}){const N=[{title:"Overview",items:cu.filter(f=>f.section==="Overview")},{title:"Systems",items:cu.filter(f=>f.section==="Systems")},{title:"URA",items:cu.filter(f=>f.section==="URA")}];return E.jsxs("aside",{className:"rail",role:"navigation","aria-label":"Dashboard sections",children:[E.jsxs("div",{className:"rail-brand",children:[E.jsx("div",{className:"rail-brand-mark",children:"U"}),E.jsxs("div",{className:"rail-brand-text",children:[E.jsx("strong",{children:"URA"}),E.jsx("span",{children:"v5.0 · p6 light"})]})]}),N.map(({title:f,items:U})=>E.jsxs("div",{children:[E.jsx("div",{className:"rail-section",children:f}),U.map(C=>{const Sa=C.icon,il=C.id===S;return E.jsxs("button",{className:`rail-link${il?" active":""}`,onClick:()=>D(C.id),"aria-current":il?"page":void 0,children:[E.jsx(Sa,{size:18,className:"icon"}),E.jsx("span",{children:C.label}),C.chip&&E.jsx("span",{className:"rail-link-chip",children:C.chip})]},C.id)})]},f))]})}const xm=[{id:"home",label:"Home",icon:Re},{id:"house",label:"House",icon:Re},{id:"zones",label:"Zones",icon:je},{id:"rooms",label:"Rooms",icon:je},{id:"energy",label:"Energy",icon:Tr},{id:"hvac",label:"HVAC",icon:zr},{id:"presence",label:"Presence",icon:wr},{id:"security",label:"Security",icon:xr},{id:"safety",label:"Safety",icon:Ar},{id:"diagnostics",label:"Diag",icon:Sr}];function zm({active:S,onChange:D}){return E.jsx("nav",{className:"mobile-tabs","aria-label":"Dashboard tabs",children:xm.map(N=>{const f=N.icon,U=N.id===S;return E.jsxs("button",{className:U?"active":"",onClick:()=>D(N.id),"aria-current":U?"page":void 0,children:[E.jsx(f,{size:16}),E.jsx("span",{children:N.label})]},N.id)})})}const Am=768;function wm({active:S,onChange:D,children:N}){return fl.useEffect(()=>{const f=document.body;f.classList.add("navet","light"),f.dataset.activeTab=S},[S]),fl.useEffect(()=>{const f=()=>{document.body.classList.toggle("mobile",window.innerWidth<=Am)};return f(),window.addEventListener("resize",f),()=>window.removeEventListener("resize",f)},[]),E.jsxs("div",{className:"app",children:[E.jsx(Sm,{active:S,onChange:D}),E.jsxs("main",{className:"main",children:[E.jsx(zm,{active:S,onChange:D}),N]})]})}const Tm=`<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <defs>
    <symbol id="lc-house" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9.5L12 2l9 7.5V21a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9.5z"/><path d="M9 22V12h6v10"/></symbol>
    <symbol id="lc-layers" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/></symbol>
    <symbol id="lc-zap" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></symbol>
    <symbol id="lc-thermo" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4 4 0 1 0 5 0z"/></symbol>
    <symbol id="lc-users" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></symbol>
    <symbol id="lc-shield" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></symbol>
    <symbol id="lc-activity" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></symbol>
    <symbol id="lc-settings" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5h0a1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/><circle cx="12" cy="12" r="3"/></symbol>
    <symbol id="lc-chevron-right" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></symbol>
    <symbol id="lc-chevron-down" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></symbol>
    <symbol id="lc-bulb" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/><path d="M9 18h6"/><path d="M10 22h4"/></symbol>
    <symbol id="lc-lock" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></symbol>
    <symbol id="lc-lock-open" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/></symbol>
    <symbol id="lc-video" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 8-6 4 6 4V8Z"/><rect width="14" height="12" x="2" y="6" rx="2"/></symbol>
    <symbol id="lc-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></symbol>
    <symbol id="lc-cloud" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 19a4.5 4.5 0 1 0-1.4-8.8 6 6 0 1 0-11.6 1.6A4 4 0 0 0 6 19h11.5Z"/></symbol>
    <symbol id="lc-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></symbol>
    <symbol id="lc-battery" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="16" height="10" rx="2"/><line x1="22" y1="11" x2="22" y2="13"/><line x1="6" y1="11" x2="6" y2="13"/><line x1="10" y1="11" x2="10" y2="13"/><line x1="14" y1="11" x2="14" y2="13"/></symbol>
    <symbol id="lc-gauge" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/></symbol>
    <symbol id="lc-alert" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></symbol>
    <symbol id="lc-brain" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/></symbol>
    <symbol id="lc-music" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></symbol>
    <symbol id="lc-fan" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.83 3.36c.13-.49.55-.86 1.06-.93C13.94 2.2 18 4.05 18 8a4 4 0 0 1-4 4"/><path d="M10 12.5C7.5 12.5 4.5 11.5 4.5 8c0-1.5 1-2.5 2-3"/><circle cx="12" cy="12" r="2"/><path d="M13.17 20.64c-.13.49-.55.86-1.06.93C10.06 21.8 6 19.95 6 16a4 4 0 0 1 4-4"/></symbol>
    <symbol id="lc-plus" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></symbol>
    <symbol id="lc-minus" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/></symbol>
    <symbol id="lc-more" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></symbol>
    <symbol id="lc-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></symbol>
    <symbol id="lc-arrow-down" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/></symbol>
    <symbol id="lc-arrow-up" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></symbol>
    <symbol id="lc-sparkles" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3z"/></symbol>
    <symbol id="lc-radio" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9"/><path d="M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5"/><circle cx="12" cy="12" r="2"/><path d="M16.2 7.8c2.3 2.3 2.3 6.1 0 8.5"/><path d="M19.1 4.9C23 8.8 23 15.1 19.1 19"/></symbol>
    <symbol id="lc-bell" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></symbol>
    <symbol id="lc-eye" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></symbol>
  </defs>
</svg>
`,Mm=`    <section class="tab active" data-tab="home">
      <header class="page-header">
        <div>
          <h1 class="page-title">Good evening, Oji</h1>
          <div class="page-subtitle">Sunday May 17 · 18:47 · Week 20</div>
        </div>
        <div class="page-actions">
          <button class="btn"><svg class="icon"><use href="#lc-bell"/></svg></button>
          <button class="btn"><svg class="icon"><use href="#lc-settings"/></svg></button>
        </div>
      </header>

      <!-- CONTROLS BAR — primary house knobs at the top -->
      <div class="controls-bar">
        <div class="knob span-4">
          <div class="knob-label">House mode <span class="badge accent">URA-suggested: Home</span></div>
          <div class="pill-group" role="tablist" aria-label="House mode" style="width:100%">
            <button class="active" style="flex:1">Home</button>
            <button style="flex:1">Sleep</button>
            <button style="flex:1">Away</button>
            <button style="flex:1">Guest</button>
            <button style="flex:1">Vacation</button>
          </div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Anomaly floor <svg class="icon-sm dim"><use href="#lc-alert"/></svg></div>
          <div class="knob-value">ALERT <span class="badge accent">3</span></div>
          <div class="knob-action">
            <input type="range" min="0" max="4" value="3" class="slider">
          </div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Battery reserve <svg class="icon-sm dim"><use href="#lc-battery"/></svg></div>
          <div class="knob-value tabular">25 <span class="dim" style="font-weight:400; font-size:var(--text-sm)">%</span></div>
          <div class="knob-action">
            <input type="range" min="10" max="80" value="25" class="slider">
          </div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Scenes</div>
          <div class="knob-action" style="margin-top:0; flex-wrap:wrap">
            <button class="btn sm">All off</button>
            <button class="btn sm">Evening</button>
            <button class="btn sm">Movie</button>
            <button class="btn sm">Bed</button>
          </div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Quick toggles</div>
          <div class="card-row"><span>Notifications</span><label class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></label></div>
          <div class="card-row"><span>Do not disturb</span><label class="toggle"><input type="checkbox"><span class="toggle-slot"></span></label></div>
        </div>
      </div>

      <!-- Status bar — at-a-glance house state -->
      <div class="status-bar">
        <div class="status-bar-item"><span class="dot green live"></span><strong>home_evening</strong></div>
        <div class="status-bar-divider"></div>
        <div class="status-bar-item"><svg class="icon-sm"><use href="#lc-cloud"/></svg><span>64°F</span><span class="dim">partly cloudy</span></div>
        <div class="status-bar-divider"></div>
        <div class="status-bar-item"><svg class="icon-sm"><use href="#lc-users"/></svg><strong>3</strong><span>/ 4 home</span></div>
        <div class="status-bar-divider"></div>
        <div class="status-bar-item"><svg class="icon-sm"><use href="#lc-zap"/></svg><strong class="tabular">0.8 kW</strong><span class="dim">from grid</span></div>
        <div class="status-bar-divider"></div>
        <div class="status-bar-item"><svg class="icon-sm"><use href="#lc-thermo"/></svg><strong class="tabular">73°F</strong><span class="dim">cool · set 72°</span></div>
        <div class="status-bar-divider"></div>
        <div class="status-bar-item"><svg class="icon-sm"><use href="#lc-shield"/></svg><span class="dim">disarmed</span></div>
        <div class="spacer"></div>
        <div class="status-bar-item"><span class="badge red"><svg class="icon-sm"><use href="#lc-alert"/></svg>2 anomalies</span></div>
      </div>

      <!-- Hero row — 4 key URA + house cards -->
      <div class="grid">
        <!-- URA brain — coordinator summary + next decision -->
        <div class="card col-6 strong">
          <div class="card-head">
            <div class="card-title"><svg class="icon-sm"><use href="#lc-brain"/></svg>URA Coordinators</div>
            <span class="badge green">5/5 healthy</span>
          </div>
          <div class="row" style="gap:var(--space-md)">
            <div>
              <div class="card-value tabular">247</div>
              <div class="card-sub">decisions today</div>
            </div>
            <div style="flex:1; border-left:1px solid var(--glass-border); padding-left:var(--space-md)">
              <div class="card-sub" style="margin-bottom:4px">Next predicted state · <span class="dim">routine awareness</span></div>
              <div class="row" style="gap:var(--space-xs)">
                <svg class="icon-sm" style="color:var(--status-blue)"><use href="#lc-moon"/></svg>
                <strong>home_night</strong>
                <span class="muted">at 21:30</span>
                <span class="badge accent">87% conf</span>
              </div>
              <div class="card-sub" style="margin-top:var(--space-xs)">
                Oji → Master Bed at 22:15 · 73% conf
              </div>
            </div>
          </div>
          <div class="card-row" style="border-top:1px solid var(--glass-border); padding-top:var(--space-sm); margin-top:var(--space-xs)">
            <span class="dim">Latest decision · 18:42</span>
            <span>HVAC · Master Suite → <span class="badge yellow">coast</span></span>
          </div>
        </div>

        <!-- Energy now -->
        <div class="card col-3 status-yellow">
          <div class="card-head">
            <div class="card-title"><svg class="icon-sm"><use href="#lc-zap"/></svg>Energy now</div>
            <span class="badge yellow">mid-peak</span>
          </div>
          <div class="card-value tabular">0.8<span class="card-unit">kW</span></div>
          <div class="card-sub">grid import · 28.4 kWh solar today</div>
          <div class="card-row"><span>Battery</span><span><strong>78%</strong> · discharging</span></div>
          <div class="card-row"><span>Cost today</span><span class="tabular">$4.82</span></div>
        </div>

        <!-- Active anomalies -->
        <div class="card col-3 status-orange">
          <div class="card-head">
            <div class="card-title"><svg class="icon-sm"><use href="#lc-alert"/></svg>Anomalies</div>
            <span class="badge orange">2 active</span>
          </div>
          <div class="card-row">
            <span class="badge red">ALERT</span>
            <span class="dim">18:31</span>
          </div>
          <div class="card-sub">HVAC · master_suite override_freq z=3.2</div>
          <div class="card-row" style="margin-top:var(--space-xs)">
            <span class="badge yellow">ADVISORY</span>
            <span class="dim">17:48</span>
          </div>
          <div class="card-sub">Presence · transitions today z=2.4</div>
        </div>
      </div>

      <!-- Section: who's home -->
      <div class="section-head">
        <h2>Who's home</h2>
        <button class="btn sm" data-tab-target="presence">View all <svg class="icon-sm"><use href="#lc-chevron-right"/></svg></button>
      </div>
      <div class="grid">
        <div class="card col-3 status-green">
          <div class="row" style="gap:var(--space-sm)">
            <div style="width:40px;height:40px;border-radius:var(--radius-full);background:linear-gradient(135deg,#42A5F5,#1E88E5);display:flex;align-items:center;justify-content:center;font-weight:600;color:white">O</div>
            <div style="flex:1">
              <div style="font-weight:600; color:var(--text-secondary); font-size:var(--text-sm)">Oji</div>
              <div style="font-weight:700; font-size:var(--text-lg); color:var(--status-green); line-height:1.1; margin-top:2px">Office</div>
            </div>
            <span class="dot green live"></span>
          </div>
          <div class="card-sub">BLE + motion · 92% confidence</div>
          <div class="card-sub">Next likely: Master Bed at 22:15</div>
        </div>
        <div class="card col-3 status-green">
          <div class="row" style="gap:var(--space-sm)">
            <div style="width:40px;height:40px;border-radius:var(--radius-full);background:linear-gradient(135deg,#EC407A,#C2185B);display:flex;align-items:center;justify-content:center;font-weight:600;color:white">E</div>
            <div style="flex:1">
              <div style="font-weight:600; color:var(--text-secondary); font-size:var(--text-sm)">Ezinne</div>
              <div style="font-weight:700; font-size:var(--text-lg); color:var(--status-green); line-height:1.1; margin-top:2px">Kitchen</div>
            </div>
            <span class="dot green live"></span>
          </div>
          <div class="card-sub">Camera + motion · 88% confidence</div>
          <div class="card-sub">Next likely: Great Room at 19:10</div>
        </div>
        <div class="card col-3 status-yellow">
          <div class="row" style="gap:var(--space-sm)">
            <div style="width:40px;height:40px;border-radius:var(--radius-full);background:linear-gradient(135deg,#66BB6A,#388E3C);display:flex;align-items:center;justify-content:center;font-weight:600;color:white">J</div>
            <div style="flex:1">
              <div style="font-weight:600; color:var(--text-secondary); font-size:var(--text-sm)">Jaya</div>
              <div style="font-weight:700; font-size:var(--text-lg); color:var(--status-yellow); line-height:1.1; margin-top:2px">Away</div>
            </div>
            <span class="dot yellow"></span>
          </div>
          <div class="card-sub">BLE not_home · since 16:12 (2h 35m)</div>
          <div class="card-sub">ETA home: ~19:30 · commute</div>
        </div>
        <div class="card col-3 status-green">
          <div class="row" style="gap:var(--space-sm)">
            <div style="width:40px;height:40px;border-radius:var(--radius-full);background:linear-gradient(135deg,#FFA726,#F57C00);display:flex;align-items:center;justify-content:center;font-weight:600;color:white">Z</div>
            <div style="flex:1">
              <div style="font-weight:600; color:var(--text-secondary); font-size:var(--text-sm)">Ziri</div>
              <div style="font-weight:700; font-size:var(--text-lg); color:var(--status-green); line-height:1.1; margin-top:2px">Playroom</div>
            </div>
            <span class="dot green live"></span>
          </div>
          <div class="card-sub">Motion + radar · 95% confidence</div>
          <div class="card-sub">Bedtime routine starts 19:30</div>
        </div>
      </div>

      <!-- Section: system quick reads -->
      <div class="section-head">
        <h2>System quick reads</h2>
      </div>
      <div class="grid">
        <!-- HVAC summary -->
        <div class="card col-4">
          <div class="card-head">
            <div class="card-title"><svg class="icon-sm"><use href="#lc-thermo"/></svg>HVAC</div>
            <button class="btn sm" data-tab-target="hvac">Details <svg class="icon-sm"><use href="#lc-chevron-right"/></svg></button>
          </div>
          <div class="row" style="gap:var(--space-md); padding:var(--space-xs) 0">
            <div>
              <div class="card-value sm tabular">73°<span class="card-unit" style="font-size:var(--text-sm)">avg</span></div>
              <div class="card-sub">set 72° · cool</div>
            </div>
            <div style="flex:1; text-align:right">
              <div class="card-sub">Comfort</div>
              <div class="tabular" style="font-size:var(--text-md);font-weight:600;color:var(--status-green)">92%</div>
            </div>
          </div>
          <div class="card-row"><span>Main Living</span><span><span class="badge green">normal</span> 72°</span></div>
          <div class="card-row"><span>Master Suite</span><span><span class="badge yellow">coast</span> 74°</span></div>
          <div class="card-row"><span>Kids</span><span><span class="badge blue">pre-cool</span> 71°</span></div>
        </div>

        <!-- Routine awareness -->
        <div class="card col-4 status-blue">
          <div class="card-head">
            <div class="card-title"><svg class="icon-sm"><use href="#lc-sparkles"/></svg>Routine awareness</div>
            <span class="badge blue">active</span>
          </div>
          <div class="card-row"><span>Next state</span><span><strong>home_night</strong> · 21:30</span></div>
          <div class="card-row"><span>Confidence</span><span class="tabular">87%</span></div>
          <div class="card-row"><span>Today's accuracy</span><span class="tabular">94% (32/34)</span></div>
          <div class="card-row"><span>Floor min severity</span><span><span class="badge accent">ALERT (3)</span></span></div>
          <div class="card-controls">
            <button class="btn sm">Floor <svg class="icon-sm"><use href="#lc-chevron-down"/></svg></button>
            <button class="btn sm">Override</button>
          </div>
        </div>

        <!-- Security summary -->
        <div class="card col-4">
          <div class="card-head">
            <div class="card-title"><svg class="icon-sm"><use href="#lc-shield"/></svg>Security</div>
            <span class="badge">disarmed</span>
          </div>
          <div class="card-row"><span>Locks</span><span><strong>4/4</strong> locked</span></div>
          <div class="card-row"><span>Cameras</span><span><strong>9</strong> recording</span></div>
          <div class="card-row"><span>Last event</span><span class="dim">Garage opened 17:54</span></div>
          <div class="card-controls">
            <div class="pill-group">
              <button>Off</button>
              <button>Home</button>
              <button>Night</button>
              <button>Away</button>
            </div>
          </div>
        </div>
      </div>

    </section>

    <!-- ====================================================
         TAB: HOUSE — aggregates only, no individual rooms
         (P2 unique: three level-tabs)
         ==================================================== -->
`,Em=`    <section class="tab" data-tab="house">
      <header class="page-header">
        <div>
          <h1 class="page-title">House</h1>
          <div class="page-subtitle">Whole-home roll-up · drill to Zones or Rooms for detail</div>
        </div>
        <div class="page-actions">
          <button class="btn"><svg class="icon"><use href="#lc-plus"/></svg> Onboard room</button>
        </div>
      </header>

      <div class="controls-bar">
        <div class="knob span-4">
          <div class="knob-label">Whole-house quick</div>
          <div class="knob-action" style="margin-top:0; flex-wrap:wrap">
            <button class="btn">All lights off</button>
            <button class="btn">Evening scene</button>
            <button class="btn">Bed scene</button>
            <button class="btn">Movie scene</button>
          </div>
        </div>
        <div class="knob span-4">
          <div class="knob-label">House climate setpoint</div>
          <div class="row" style="gap:var(--space-xs); align-items:center">
            <button class="btn icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button>
            <div class="knob-value tabular" style="flex:1; text-align:center">72°</div>
            <button class="btn icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button>
          </div>
          <div class="card-sub">All zones · per-zone offsets retained</div>
        </div>
        <div class="knob span-4">
          <div class="knob-label">Drill into</div>
          <div class="knob-action" style="margin-top:0; flex-wrap:wrap">
            <button class="btn" data-tab-target="zones">Zones <svg class="icon-sm"><use href="#lc-chevron-right"/></svg></button>
            <button class="btn" data-tab-target="rooms">Rooms <svg class="icon-sm"><use href="#lc-chevron-right"/></svg></button>
          </div>
        </div>
      </div>

      <!-- Whole-house KPI -->
      <div class="grid">
        <div class="card col-3">
          <div class="card-title">Occupancy</div>
          <div class="card-value tabular">3<span class="card-unit">/ 4</span></div>
          <div class="card-sub">8 rooms occupied · 11 idle</div>
        </div>
        <div class="card col-3">
          <div class="card-title">Lights on</div>
          <div class="card-value tabular">23<span class="card-unit">/ 87</span></div>
          <div class="card-sub">Main: 12 · Kids: 6 · Master: 5</div>
        </div>
        <div class="card col-3">
          <div class="card-title">Avg temperature</div>
          <div class="card-value tabular">73°<span class="card-unit">F</span></div>
          <div class="card-sub">range 71° – 76° · outside 64°</div>
        </div>
        <div class="card col-3">
          <div class="card-title">Activity (5 min)</div>
          <div class="card-value tabular">14</div>
          <div class="card-sub">motion events · 3 zones</div>
        </div>
      </div>

      <!-- House-level summaries -->
      <div class="section-head"><h2>Zone roll-ups</h2></div>
      <div class="grid">
        <div class="card col-4 status-green">
          <div class="card-head"><div class="row" style="gap:var(--space-xs)"><span class="dot green live"></span><strong>Main Living</strong></div><button class="btn sm" data-tab-target="zones">View</button></div>
          <div class="card-row"><span>Occupied</span><span class="tabular">3 / 5 rooms</span></div>
          <div class="card-row"><span>Lights</span><span class="tabular">12 / 18 on</span></div>
          <div class="card-row"><span>Temp / target</span><span class="tabular">72° / 72°</span></div>
          <div class="card-row"><span>Status</span><span><span class="badge green">normal</span></span></div>
        </div>
        <div class="card col-4 status-yellow">
          <div class="card-head"><div class="row" style="gap:var(--space-xs)"><span class="dot green"></span><strong>Master Suite</strong></div><button class="btn sm" data-tab-target="zones">View</button></div>
          <div class="card-row"><span>Occupied</span><span class="tabular">1 / 4 rooms</span></div>
          <div class="card-row"><span>Lights</span><span class="tabular">5 / 12 on</span></div>
          <div class="card-row"><span>Temp / target</span><span class="tabular">74° / 73°</span></div>
          <div class="card-row"><span>Status</span><span><span class="badge yellow">coast</span></span></div>
        </div>
        <div class="card col-4 status-blue">
          <div class="card-head"><div class="row" style="gap:var(--space-xs)"><span class="dot green live"></span><strong>Kids</strong></div><button class="btn sm" data-tab-target="zones">View</button></div>
          <div class="card-row"><span>Occupied</span><span class="tabular">1 / 4 rooms</span></div>
          <div class="card-row"><span>Lights</span><span class="tabular">6 / 11 on</span></div>
          <div class="card-row"><span>Temp / target</span><span class="tabular">71° / 71°</span></div>
          <div class="card-row"><span>Status</span><span><span class="badge blue">pre-cool</span></span></div>
        </div>
        <div class="card col-6">
          <div class="card-head"><div class="row" style="gap:var(--space-xs)"><span class="dot grey"></span><strong>Guest</strong></div><button class="btn sm" data-tab-target="zones">View</button></div>
          <div class="card-row"><span>Occupied</span><span class="tabular">0 / 3 rooms</span></div>
          <div class="card-row"><span>Lights</span><span class="tabular">0 / 7 on</span></div>
          <div class="card-row"><span>Temp / target</span><span class="tabular">75° / 78°</span></div>
          <div class="card-row"><span>Status</span><span><span class="badge">setback · vacancy</span></span></div>
        </div>
        <div class="card col-6">
          <div class="card-head"><div class="row" style="gap:var(--space-xs)"><span class="dot grey"></span><strong>Outdoor</strong></div><button class="btn sm" data-tab-target="zones">View</button></div>
          <div class="card-row"><span>Active</span><span class="dim">— · 0 sensors triggered</span></div>
          <div class="card-row"><span>Lights</span><span class="tabular">0 / 6 on</span></div>
          <div class="card-row"><span>Outdoor temp</span><span class="tabular">64° · partly cloudy</span></div>
          <div class="card-row"><span>Status</span><span><span class="badge">sunset 19:42</span></span></div>
        </div>
      </div>
    </section>

    <!-- ====================================================
         TAB: ZONES — 5 zone cards with room roll-ups
         ==================================================== -->
`,Om=`    <section class="tab" data-tab="zones">
      <header class="page-header">
        <div>
          <h1 class="page-title">Zones</h1>
          <div class="page-subtitle">5 zones · tap a zone to filter Rooms tab</div>
        </div>
        <div class="page-actions">
          <button class="btn sm" data-tab-target="rooms">All rooms <svg class="icon-sm"><use href="#lc-chevron-right"/></svg></button>
        </div>
      </header>

      <div class="controls-bar">
        <div class="knob span-4">
          <div class="knob-label">Sort by</div>
          <div class="pill-group" style="width:100%">
            <button class="active" style="flex:1">Occupancy</button>
            <button style="flex:1">Lights on</button>
            <button style="flex:1">Demand</button>
            <button style="flex:1">Name</button>
          </div>
        </div>
        <div class="knob span-4">
          <div class="knob-label">Show zones</div>
          <div class="pill-group" style="width:100%">
            <button class="active" style="flex:1">All</button>
            <button style="flex:1">Indoor</button>
            <button style="flex:1">Active</button>
          </div>
        </div>
        <div class="knob span-4">
          <div class="knob-label">Whole-house</div>
          <div class="knob-action" style="margin-top:0; flex-wrap:wrap">
            <button class="btn">All lights off</button>
            <button class="btn">Setback all</button>
          </div>
        </div>
      </div>

      <div class="grid">
        <div class="card col-6 status-green">
          <div class="card-head">
            <div class="row" style="gap:var(--space-xs); font-size:var(--text-lg)"><span class="dot green live"></span><strong>Main Living</strong></div>
            <span class="badge green">normal · cooling</span>
          </div>
          <div class="row" style="gap:var(--space-md); padding:var(--space-xs) 0">
            <div><div class="card-value sm tabular">3 / 5</div><div class="card-sub">occupied</div></div>
            <div><div class="card-value sm tabular">72°</div><div class="card-sub">avg · set 72°</div></div>
            <div><div class="card-value sm tabular">12 / 18</div><div class="card-sub">lights on</div></div>
            <div style="flex:1"></div>
          </div>
          <div class="card-row"><span>Rooms</span><span class="dim">Great Room · Kitchen · Dining · Foyer · Hallway</span></div>
          <div class="card-controls">
            <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button>
            <span class="tabular" style="font-size:var(--text-md); align-self:center; padding:0 4px">72°</span>
            <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button>
            <button class="btn sm">All lights off</button>
            <button class="btn sm" data-tab-target="rooms">Open rooms <svg class="icon-sm"><use href="#lc-chevron-right"/></svg></button>
          </div>
        </div>
        <div class="card col-6 status-yellow">
          <div class="card-head">
            <div class="row" style="gap:var(--space-xs); font-size:var(--text-lg)"><span class="dot green"></span><strong>Master Suite</strong></div>
            <span class="badge yellow">coast</span>
          </div>
          <div class="row" style="gap:var(--space-md); padding:var(--space-xs) 0">
            <div><div class="card-value sm tabular">1 / 4</div><div class="card-sub">occupied (Oji)</div></div>
            <div><div class="card-value sm tabular">74°</div><div class="card-sub">avg · set 73°</div></div>
            <div><div class="card-value sm tabular">5 / 12</div><div class="card-sub">lights on</div></div>
            <div style="flex:1"></div>
          </div>
          <div class="card-row"><span>Rooms</span><span class="dim">Office · Master Bed · Master Bath · Master Closet</span></div>
          <div class="card-row"><span>URA reason</span><span class="dim">occupancy drop predicted 45m</span></div>
          <div class="card-controls">
            <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button>
            <span class="tabular" style="font-size:var(--text-md); align-self:center; padding:0 4px">73°</span>
            <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button>
            <button class="btn sm">All lights off</button>
            <button class="btn sm" data-tab-target="rooms">Open rooms <svg class="icon-sm"><use href="#lc-chevron-right"/></svg></button>
          </div>
        </div>
        <div class="card col-6 status-blue">
          <div class="card-head">
            <div class="row" style="gap:var(--space-xs); font-size:var(--text-lg)"><span class="dot green live"></span><strong>Kids</strong></div>
            <span class="badge blue">pre-cool</span>
          </div>
          <div class="row" style="gap:var(--space-md); padding:var(--space-xs) 0">
            <div><div class="card-value sm tabular">1 / 4</div><div class="card-sub">occupied (Ziri)</div></div>
            <div><div class="card-value sm tabular">71°</div><div class="card-sub">avg · set 71°</div></div>
            <div><div class="card-value sm tabular">6 / 11</div><div class="card-sub">lights on</div></div>
            <div style="flex:1"></div>
          </div>
          <div class="card-row"><span>Rooms</span><span class="dim">Playroom · Ziri Bed · Ziri Bath · Study</span></div>
          <div class="card-row"><span>URA reason</span><span class="dim">Ziri bedtime routine 19:30</span></div>
          <div class="card-controls">
            <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button>
            <span class="tabular" style="font-size:var(--text-md); align-self:center; padding:0 4px">71°</span>
            <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button>
            <button class="btn sm">All lights off</button>
            <button class="btn sm" data-tab-target="rooms">Open rooms <svg class="icon-sm"><use href="#lc-chevron-right"/></svg></button>
          </div>
        </div>
        <div class="card col-6">
          <div class="card-head">
            <div class="row" style="gap:var(--space-xs); font-size:var(--text-lg)"><span class="dot grey"></span><strong>Guest</strong></div>
            <span class="badge">setback</span>
          </div>
          <div class="row" style="gap:var(--space-md); padding:var(--space-xs) 0">
            <div><div class="card-value sm tabular">0 / 3</div><div class="card-sub">occupied</div></div>
            <div><div class="card-value sm tabular">75°</div><div class="card-sub">avg · set 78°</div></div>
            <div><div class="card-value sm tabular">0 / 7</div><div class="card-sub">lights on</div></div>
            <div style="flex:1"></div>
          </div>
          <div class="card-row"><span>Rooms</span><span class="dim">Guest Bed · Guest Bath · Gym</span></div>
          <div class="card-row"><span>URA reason</span><span class="dim">vacancy economy · guest mode off</span></div>
          <div class="card-controls">
            <button class="btn sm">Wake zone</button>
            <button class="btn sm">Guest mode on</button>
            <button class="btn sm" data-tab-target="rooms">Open rooms <svg class="icon-sm"><use href="#lc-chevron-right"/></svg></button>
          </div>
        </div>
        <div class="card col-12">
          <div class="card-head">
            <div class="row" style="gap:var(--space-xs); font-size:var(--text-lg)"><span class="dot grey"></span><strong>Outdoor</strong></div>
            <span class="badge">sunset 19:42</span>
          </div>
          <div class="row" style="gap:var(--space-md); padding:var(--space-xs) 0">
            <div><div class="card-value sm tabular">64°</div><div class="card-sub">outdoor · partly cloudy</div></div>
            <div><div class="card-value sm tabular">0 / 6</div><div class="card-sub">lights on (auto at sunset)</div></div>
            <div><div class="card-value sm tabular">5.4 mph</div><div class="card-sub">wind · S</div></div>
            <div><div class="card-value sm tabular">0.0&quot;</div><div class="card-sub">rain today</div></div>
            <div style="flex:1"></div>
          </div>
          <div class="card-row"><span>Rooms</span><span class="dim">Front Porch · Back Deck · Garage</span></div>
          <div class="card-controls">
            <button class="btn sm">Porch on</button>
            <button class="btn sm">Deck on</button>
            <button class="btn sm">Auto sunset</button>
            <button class="btn sm" data-tab-target="rooms">Open rooms <svg class="icon-sm"><use href="#lc-chevron-right"/></svg></button>
          </div>
        </div>
      </div>
    </section>

    <!-- ====================================================
         TAB: ROOMS — dense grid of every room with controls
         ==================================================== -->
`,Dm=`    <section class="tab" data-tab="rooms">
      <header class="page-header">
        <div>
          <h1 class="page-title">Rooms</h1>
          <div class="page-subtitle">19 rooms · auto-onboarded · controls per room</div>
        </div>
        <div class="page-actions">
          <button class="btn"><svg class="icon"><use href="#lc-plus"/></svg> Onboard room</button>
        </div>
      </header>

      <div class="controls-bar">
        <div class="knob span-3">
          <div class="knob-label">Zone filter</div>
          <div class="pill-group" style="width:100%; flex-wrap:wrap">
            <button class="active" style="flex:1">All</button>
            <button style="flex:1">Main</button>
            <button style="flex:1">Master</button>
            <button style="flex:1">Kids</button>
            <button style="flex:1">Guest</button>
            <button style="flex:1">Outdoor</button>
          </div>
        </div>
        <div class="knob span-3">
          <div class="knob-label">Show only</div>
          <div class="pill-group" style="width:100%">
            <button class="active" style="flex:1">All</button>
            <button style="flex:1">Occupied</button>
            <button style="flex:1">Lights on</button>
            <button style="flex:1">Climate</button>
          </div>
        </div>
        <div class="knob span-3">
          <div class="knob-label">Sort by</div>
          <div class="pill-group" style="width:100%">
            <button class="active" style="flex:1">Zone</button>
            <button style="flex:1">Occupancy</button>
            <button style="flex:1">Temp</button>
            <button style="flex:1">Name</button>
          </div>
        </div>
        <div class="knob span-3">
          <div class="knob-label">Bulk actions</div>
          <div class="knob-action" style="margin-top:0; flex-wrap:wrap">
            <button class="btn sm">Lights off · filtered</button>
            <button class="btn sm">Setback · filtered</button>
          </div>
        </div>
      </div>

      <!-- Zone headers + dense room grid -->
      <div class="section-head"><h2>Main Living · 5 rooms</h2><span class="dim">3 occupied · 12/18 lights</span></div>
      <div class="grid">
        <div class="room-card col-3 status-green"><div class="room-card-head"><span class="dot green live"></span><span class="room-card-title">Great Room</span></div><div class="room-card-meta"><span><svg class="icon-sm"><use href="#lc-thermo"/></svg>72°</span><span><svg class="icon-sm"><use href="#lc-bulb"/></svg>4/6</span><span><svg class="icon-sm"><use href="#lc-fan"/></svg>med</span></div><div class="room-card-controls"><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-bulb"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button><span class="tabular" style="font-size:var(--text-sm); align-self:center; padding:0 4px">72°</span><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
        <div class="room-card col-3 status-green"><div class="room-card-head"><span class="dot green live"></span><span class="room-card-title">Kitchen</span></div><div class="room-card-meta"><span><svg class="icon-sm"><use href="#lc-thermo"/></svg>72°</span><span><svg class="icon-sm"><use href="#lc-bulb"/></svg>5/5</span><span><svg class="icon-sm"><use href="#lc-music"/></svg>•</span></div><div class="room-card-controls"><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-bulb"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button><span class="tabular" style="font-size:var(--text-sm); align-self:center; padding:0 4px">72°</span><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
        <div class="room-card col-3"><div class="room-card-head"><span class="dot green"></span><span class="room-card-title">Dining Room</span></div><div class="room-card-meta"><span><svg class="icon-sm"><use href="#lc-thermo"/></svg>72°</span><span><svg class="icon-sm"><use href="#lc-bulb"/></svg>0/3</span><span class="dim">idle 4h</span></div><div class="room-card-controls"><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-bulb"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button><span class="tabular" style="font-size:var(--text-sm); align-self:center; padding:0 4px">72°</span><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
        <div class="room-card col-3"><div class="room-card-head"><span class="dot grey"></span><span class="room-card-title">Foyer</span></div><div class="room-card-meta"><span><svg class="icon-sm"><use href="#lc-thermo"/></svg>73°</span><span><svg class="icon-sm"><use href="#lc-bulb"/></svg>1/2</span><span class="dim">auto</span></div><div class="room-card-controls"><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-bulb"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button><span class="tabular" style="font-size:var(--text-sm); align-self:center; padding:0 4px">72°</span><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
        <div class="room-card col-3"><div class="room-card-head"><span class="dot grey"></span><span class="room-card-title">Hallway</span></div><div class="room-card-meta"><span><svg class="icon-sm"><use href="#lc-thermo"/></svg>73°</span><span><svg class="icon-sm"><use href="#lc-bulb"/></svg>2/4</span><span class="dim">auto</span></div><div class="room-card-controls"><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-bulb"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button><span class="tabular" style="font-size:var(--text-sm); align-self:center; padding:0 4px">72°</span><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
      </div>

      <div class="section-head"><h2>Master Suite · 4 rooms</h2><span class="dim">1 occupied · 5/12 lights · <span class="badge yellow">coast</span></span></div>
      <div class="grid">
        <div class="room-card col-3 status-green"><div class="room-card-head"><span class="dot green live"></span><span class="room-card-title">Office</span><span class="badge green">Oji</span></div><div class="room-card-meta"><span><svg class="icon-sm"><use href="#lc-thermo"/></svg>73°</span><span><svg class="icon-sm"><use href="#lc-bulb"/></svg>2/3</span><span><svg class="icon-sm"><use href="#lc-music"/></svg>•</span></div><div class="room-card-controls"><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-bulb"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button><span class="tabular" style="font-size:var(--text-sm); align-self:center; padding:0 4px">72°</span><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
        <div class="room-card col-3 status-yellow"><div class="room-card-head"><span class="dot yellow"></span><span class="room-card-title">Master Bed</span><span class="badge yellow">coast</span></div><div class="room-card-meta"><span><svg class="icon-sm"><use href="#lc-thermo"/></svg>74°</span><span><svg class="icon-sm"><use href="#lc-bulb"/></svg>0/2</span></div><div class="room-card-controls"><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-bulb"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button><span class="tabular" style="font-size:var(--text-sm); align-self:center; padding:0 4px">73°</span><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
        <div class="room-card col-3"><div class="room-card-head"><span class="dot grey"></span><span class="room-card-title">Master Bath</span></div><div class="room-card-meta"><span><svg class="icon-sm"><use href="#lc-thermo"/></svg>74°</span><span><svg class="icon-sm"><use href="#lc-bulb"/></svg>0/3</span></div><div class="room-card-controls"><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-bulb"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button><span class="tabular" style="font-size:var(--text-sm); align-self:center; padding:0 4px">73°</span><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
        <div class="room-card col-3"><div class="room-card-head"><span class="dot grey"></span><span class="room-card-title">Master Closet</span></div><div class="room-card-meta"><span><svg class="icon-sm"><use href="#lc-bulb"/></svg>0/2</span><span class="dim">no climate</span></div><div class="room-card-controls"><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-bulb"/></svg></button><button class="btn sm icon" disabled><svg class="icon-sm"><use href="#lc-minus"/></svg></button><span class="dim tabular" style="font-size:var(--text-sm); align-self:center; padding:0 4px">—</span><button class="btn sm icon" disabled><svg class="icon-sm"><use href="#lc-plus"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
      </div>

      <div class="section-head"><h2>Kids · 4 rooms</h2><span class="dim">1 occupied · 6/11 lights · <span class="badge blue">pre-cool</span></span></div>
      <div class="grid">
        <div class="room-card col-3 status-blue"><div class="room-card-head"><span class="dot green live"></span><span class="room-card-title">Playroom</span><span class="badge green">Ziri</span></div><div class="room-card-meta"><span><svg class="icon-sm"><use href="#lc-thermo"/></svg>71°</span><span><svg class="icon-sm"><use href="#lc-bulb"/></svg>3/4</span></div><div class="room-card-controls"><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-bulb"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button><span class="tabular" style="font-size:var(--text-sm); align-self:center; padding:0 4px">71°</span><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
        <div class="room-card col-3 status-blue"><div class="room-card-head"><span class="dot grey"></span><span class="room-card-title">Ziri Bed</span><span class="badge blue">pre-cool</span></div><div class="room-card-meta"><span><svg class="icon-sm"><use href="#lc-thermo"/></svg>72°</span><span><svg class="icon-sm"><use href="#lc-bulb"/></svg>1/2</span></div><div class="room-card-controls"><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-bulb"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button><span class="tabular" style="font-size:var(--text-sm); align-self:center; padding:0 4px">71°</span><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
        <div class="room-card col-3"><div class="room-card-head"><span class="dot grey"></span><span class="room-card-title">Ziri Bath</span></div><div class="room-card-meta"><span><svg class="icon-sm"><use href="#lc-thermo"/></svg>73°</span><span><svg class="icon-sm"><use href="#lc-bulb"/></svg>0/2</span></div><div class="room-card-controls"><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-bulb"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button><span class="tabular" style="font-size:var(--text-sm); align-self:center; padding:0 4px">72°</span><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
        <div class="room-card col-3"><div class="room-card-head"><span class="dot grey"></span><span class="room-card-title">Study</span></div><div class="room-card-meta"><span><svg class="icon-sm"><use href="#lc-thermo"/></svg>72°</span><span><svg class="icon-sm"><use href="#lc-bulb"/></svg>2/3</span></div><div class="room-card-controls"><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-bulb"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button><span class="tabular" style="font-size:var(--text-sm); align-self:center; padding:0 4px">71°</span><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
      </div>

      <div class="section-head"><h2>Guest · 3 rooms</h2><span class="dim">vacancy economy · setback</span></div>
      <div class="grid">
        <div class="room-card col-4"><div class="room-card-head"><span class="dot grey"></span><span class="room-card-title">Guest Bed</span></div><div class="room-card-meta"><span><svg class="icon-sm"><use href="#lc-thermo"/></svg>76°</span><span><svg class="icon-sm"><use href="#lc-bulb"/></svg>0/2</span><span class="dim">setback</span></div><div class="room-card-controls"><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-bulb"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button><span class="tabular" style="font-size:var(--text-sm); align-self:center; padding:0 4px">78°</span><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
        <div class="room-card col-4"><div class="room-card-head"><span class="dot grey"></span><span class="room-card-title">Guest Bath</span></div><div class="room-card-meta"><span><svg class="icon-sm"><use href="#lc-thermo"/></svg>75°</span><span><svg class="icon-sm"><use href="#lc-bulb"/></svg>0/2</span></div><div class="room-card-controls"><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-bulb"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button><span class="tabular" style="font-size:var(--text-sm); align-self:center; padding:0 4px">78°</span><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
        <div class="room-card col-4"><div class="room-card-head"><span class="dot grey"></span><span class="room-card-title">Gym</span></div><div class="room-card-meta"><span><svg class="icon-sm"><use href="#lc-thermo"/></svg>74°</span><span><svg class="icon-sm"><use href="#lc-bulb"/></svg>0/3</span></div><div class="room-card-controls"><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-bulb"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button><span class="tabular" style="font-size:var(--text-sm); align-self:center; padding:0 4px">76°</span><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
      </div>

      <div class="section-head"><h2>Outdoor · 3 rooms</h2><span class="dim">sunset 19:42 · auto-on</span></div>
      <div class="grid">
        <div class="room-card col-4"><div class="room-card-head"><span class="dot grey"></span><span class="room-card-title">Front Porch</span></div><div class="room-card-meta"><span class="dim">outdoor 64°</span><span><svg class="icon-sm"><use href="#lc-bulb"/></svg>0/1</span></div><div class="room-card-controls"><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-bulb"/></svg></button><button class="btn sm">Auto sunset</button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
        <div class="room-card col-4"><div class="room-card-head"><span class="dot grey"></span><span class="room-card-title">Back Deck</span></div><div class="room-card-meta"><span class="dim">outdoor 64°</span><span><svg class="icon-sm"><use href="#lc-bulb"/></svg>0/2</span></div><div class="room-card-controls"><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-bulb"/></svg></button><button class="btn sm">Auto sunset</button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
        <div class="room-card col-4"><div class="room-card-head"><span class="dot grey"></span><span class="room-card-title">Garage</span><span class="badge">closed</span></div><div class="room-card-meta"><span class="dim">last opened 17:54</span></div><div class="room-card-controls"><button class="btn sm">Open</button><button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button></div></div>
      </div>
    </section>

    <!-- ====================================================
         TAB: ENERGY
         ==================================================== -->
`,Bm=`    <section class="tab" data-tab="energy">
      <header class="page-header">
        <div>
          <h1 class="page-title">Energy</h1>
          <div class="page-subtitle">TOU · mid-peak · peak begins 19:00 · 13 min</div>
        </div>
        <div class="page-actions">
          <span class="badge yellow lg">mid-peak · $0.18/kWh</span>
        </div>
      </header>

      <!-- CONTROLS BAR — energy coordinator knobs -->
      <div class="controls-bar">
        <div class="knob span-3">
          <div class="knob-label">Battery reserve <span class="badge accent">URA: 25%</span></div>
          <div class="knob-value tabular">25 <span class="dim" style="font-weight:400; font-size:var(--text-sm)">% · 12.5 kWh</span></div>
          <div class="knob-action">
            <input type="range" min="10" max="80" value="25" class="slider">
          </div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Grid import cap</div>
          <div class="knob-value tabular">8.0 <span class="dim" style="font-weight:400; font-size:var(--text-sm)">kW</span></div>
          <div class="knob-action">
            <input type="range" min="2" max="15" value="8" class="slider">
          </div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">EV charge max</div>
          <div class="knob-value tabular">7.2 <span class="dim" style="font-weight:400; font-size:var(--text-sm)">kW</span></div>
          <div class="knob-action">
            <input type="range" min="1" max="12" value="7" class="slider">
          </div>
        </div>
        <div class="knob span-3">
          <div class="knob-label">Battery mode</div>
          <div class="pill-group" style="width:100%">
            <button class="active" style="flex:1">Self-consumption</button>
            <button style="flex:1">Storm reserve</button>
            <button style="flex:1">TOU shift</button>
          </div>
          <div class="card-sub">Locked per codicil · cannot use grid_charge</div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Manual</div>
          <div class="knob-action" style="margin-top:0; flex-direction:column; align-items:stretch">
            <button class="btn danger">Shed loads now</button>
            <button class="btn sm">Resume EV</button>
          </div>
        </div>
      </div>

      <!-- Hero KPI row -->
      <div class="grid">
        <div class="card col-3 status-yellow">
          <div class="card-title"><svg class="icon-sm"><use href="#lc-sun"/></svg>Solar now</div>
          <div class="card-value tabular">0.4<span class="card-unit">kW</span></div>
          <div class="card-sub">28.4 kWh today · forecast 32.1</div>
        </div>
        <div class="card col-3 status-green">
          <div class="card-title"><svg class="icon-sm"><use href="#lc-battery"/></svg>Battery</div>
          <div class="card-value tabular">78<span class="card-unit">%</span></div>
          <div class="card-sub">discharging 1.2 kW · reserve 25%</div>
          <div class="gauge-track"><div class="gauge-fill" style="width:78%"></div></div>
        </div>
        <div class="card col-3 status-orange">
          <div class="card-title"><svg class="icon-sm"><use href="#lc-zap"/></svg>Grid</div>
          <div class="card-value tabular">+0.8<span class="card-unit">kW</span></div>
          <div class="card-sub">importing · 5.4 kWh today</div>
        </div>
        <div class="card col-3">
          <div class="card-title">Cost today</div>
          <div class="card-value tabular">$4.82</div>
          <div class="card-sub">predicted bill: <strong class="tabular">$147</strong> (May)</div>
        </div>
      </div>

      <!-- Energy flow + Solcast chart -->
      <div class="grid" style="margin-top:var(--space-lg)">
        <div class="card col-7">
          <div class="card-head">
            <div class="card-title"><svg class="icon-sm"><use href="#lc-activity"/></svg>Solar — Solcast vs actual (today)</div>
            <span class="dim">refreshed 18:45</span>
          </div>
          <svg viewBox="0 0 600 180" class="sparkline" style="height:180px" preserveAspectRatio="none">
            <defs>
              <linearGradient id="solar-grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#FFCA28" stop-opacity="0.4"/>
                <stop offset="100%" stop-color="#FFCA28" stop-opacity="0"/>
              </linearGradient>
            </defs>
            <!-- grid lines -->
            <line x1="0" y1="45" x2="600" y2="45" stroke="rgba(255,255,255,0.05)"/>
            <line x1="0" y1="90" x2="600" y2="90" stroke="rgba(255,255,255,0.05)"/>
            <line x1="0" y1="135" x2="600" y2="135" stroke="rgba(255,255,255,0.05)"/>
            <!-- forecast (dashed) -->
            <path d="M0 170 Q60 168 100 150 T200 60 T300 30 T400 50 T500 130 T600 170" fill="none" stroke="rgba(130,177,255,0.5)" stroke-width="1.5" stroke-dasharray="3,3"/>
            <!-- actual (solid + gradient fill) -->
            <path d="M0 175 Q60 172 100 155 T200 65 T300 38 T380 55 T420 75 L420 75 L420 175 Z" fill="url(#solar-grad)"/>
            <path d="M0 175 Q60 172 100 155 T200 65 T300 38 T380 55 T420 75" fill="none" stroke="#FFCA28" stroke-width="2"/>
            <!-- now marker -->
            <line x1="430" y1="0" x2="430" y2="180" stroke="rgba(255,255,255,0.15)" stroke-dasharray="2,2"/>
            <circle cx="430" cy="120" r="3" fill="#FFCA28"/>
            <text x="435" y="115" fill="rgba(255,255,255,0.6)" font-size="10">now · 0.4 kW</text>
            <!-- x-axis -->
            <text x="0" y="178" fill="rgba(255,255,255,0.4)" font-size="9">06</text>
            <text x="150" y="178" fill="rgba(255,255,255,0.4)" font-size="9">10</text>
            <text x="300" y="178" fill="rgba(255,255,255,0.4)" font-size="9">14</text>
            <text x="450" y="178" fill="rgba(255,255,255,0.4)" font-size="9">18</text>
            <text x="585" y="178" fill="rgba(255,255,255,0.4)" font-size="9">22</text>
          </svg>
          <div class="row" style="gap:var(--space-md); font-size:var(--text-xs); color:var(--text-tertiary)">
            <span><span class="dot yellow" style="display:inline-block"></span> actual</span>
            <span><span class="dot blue" style="display:inline-block"></span> Solcast forecast</span>
            <span class="spacer"></span>
            <span>peak today: <strong class="tabular">5.2 kW</strong> @ 12:48</span>
          </div>
        </div>

        <div class="card col-5">
          <div class="card-head">
            <div class="card-title"><svg class="icon-sm"><use href="#lc-zap"/></svg>Energy flow (live)</div>
            <span class="badge green">streaming</span>
          </div>
          <svg viewBox="0 0 320 220" style="width:100%; height:220px">
            <!-- Solar -->
            <g transform="translate(20,20)">
              <rect x="0" y="0" width="80" height="50" rx="10" fill="rgba(255,202,40,0.12)" stroke="#FFCA28" stroke-width="1"/>
              <text x="40" y="22" text-anchor="middle" fill="#FFCA28" font-size="11" font-weight="600">Solar</text>
              <text x="40" y="40" text-anchor="middle" fill="#FFCA28" font-size="14" font-weight="500">0.4 kW</text>
            </g>
            <!-- Battery -->
            <g transform="translate(20,150)">
              <rect x="0" y="0" width="80" height="50" rx="10" fill="rgba(102,187,106,0.12)" stroke="#66BB6A" stroke-width="1"/>
              <text x="40" y="22" text-anchor="middle" fill="#66BB6A" font-size="11" font-weight="600">Battery</text>
              <text x="40" y="40" text-anchor="middle" fill="#66BB6A" font-size="14" font-weight="500">78% · -1.2</text>
            </g>
            <!-- Grid -->
            <g transform="translate(220,150)">
              <rect x="0" y="0" width="80" height="50" rx="10" fill="rgba(255,167,38,0.12)" stroke="#FFA726" stroke-width="1"/>
              <text x="40" y="22" text-anchor="middle" fill="#FFA726" font-size="11" font-weight="600">Grid</text>
              <text x="40" y="40" text-anchor="middle" fill="#FFA726" font-size="14" font-weight="500">+0.8 kW</text>
            </g>
            <!-- House -->
            <g transform="translate(220,20)">
              <rect x="0" y="0" width="80" height="50" rx="10" fill="rgba(130,177,255,0.12)" stroke="#82B1FF" stroke-width="1"/>
              <text x="40" y="22" text-anchor="middle" fill="#82B1FF" font-size="11" font-weight="600">House</text>
              <text x="40" y="40" text-anchor="middle" fill="#82B1FF" font-size="14" font-weight="500">2.4 kW</text>
            </g>
            <!-- arrows -->
            <path d="M100 45 L220 45" stroke="#FFCA28" stroke-width="2" marker-end="url(#arrow-y)"/>
            <path d="M100 175 L220 50" stroke="#66BB6A" stroke-width="2" marker-end="url(#arrow-g)"/>
            <path d="M260 150 L260 70" stroke="#FFA726" stroke-width="2" marker-end="url(#arrow-o)"/>
            <defs>
              <marker id="arrow-y" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><polygon points="0 0, 6 4, 0 8" fill="#FFCA28"/></marker>
              <marker id="arrow-g" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><polygon points="0 0, 6 4, 0 8" fill="#66BB6A"/></marker>
              <marker id="arrow-o" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><polygon points="0 0, 6 4, 0 8" fill="#FFA726"/></marker>
            </defs>
          </svg>
          <div class="card-sub" style="text-align:center">Net to house: solar 0.4 + battery 1.2 + grid 0.8 = 2.4 kW</div>
        </div>
      </div>

      <!-- URA brain: energy decisions + tariff timeline -->
      <div class="grid" style="margin-top:var(--space-lg)">
        <div class="card col-8">
          <div class="card-head">
            <div class="card-title"><svg class="icon-sm"><use href="#lc-brain"/></svg>URA · recent energy decisions</div>
          </div>
          <div class="timeline">
            <div class="timeline-row">
              <div class="timeline-time">18:30</div>
              <div class="timeline-body">
                <div class="timeline-headline"><span class="badge accent">Battery</span> Reserve raised to <strong>25%</strong></div>
                <div class="timeline-reason">TOU peak begins 19:00 · hold capacity for peak shave</div>
              </div>
              <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button>
            </div>
            <div class="timeline-row">
              <div class="timeline-time">17:55</div>
              <div class="timeline-body">
                <div class="timeline-headline"><span class="badge accent">HVAC</span> Pre-cool authorized · Kids zone</div>
                <div class="timeline-reason">Solar surplus 2.1 kW · use before peak</div>
              </div>
              <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button>
            </div>
            <div class="timeline-row">
              <div class="timeline-time">15:42</div>
              <div class="timeline-body">
                <div class="timeline-headline"><span class="badge accent">EV</span> Charge paused</div>
                <div class="timeline-reason">Grid import threshold exceeded · resume at off-peak</div>
              </div>
              <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button>
            </div>
          </div>
        </div>

        <div class="card col-4">
          <div class="card-title">Today's tariff</div>
          <div class="row" style="gap:0; height:24px; margin:var(--space-sm) 0; border-radius:var(--radius-sm); overflow:hidden">
            <div style="flex:6; background:rgba(102,187,106,0.5)" title="off-peak"></div>
            <div style="flex:6; background:rgba(255,202,40,0.5)" title="mid"></div>
            <div style="flex:5; background:rgba(239,83,80,0.6)" title="peak"></div>
            <div style="flex:3; background:rgba(255,202,40,0.5)" title="mid"></div>
            <div style="flex:4; background:rgba(102,187,106,0.5)" title="off-peak"></div>
          </div>
          <div class="card-row"><span>Off-peak</span><span class="tabular">12h · $0.08</span></div>
          <div class="card-row"><span>Mid-peak <span class="badge yellow">now</span></span><span class="tabular">9h · $0.18</span></div>
          <div class="card-row"><span>Peak</span><span class="tabular">3h · $0.36</span></div>
        </div>
      </div>

      <!-- Load detail (status only — controls are at top) -->
      <div class="section-head"><h2>Load status</h2></div>
      <div class="grid">
        <div class="card col-4"><div class="card-row"><span>EV charging</span><span class="badge orange">paused · TOU</span></div><div class="card-row"><span>Pool pump</span><span class="badge green">off</span></div><div class="card-row"><span>Hot tub</span><span class="badge">scheduled 02:00</span></div><div class="card-row"><span>Dryer</span><span class="dim">finished 17:12</span></div></div>
        <div class="card col-4"><div class="card-head"><div class="card-title">Generator</div><span class="badge">standby</span></div><div class="card-row"><span>Fuel</span><span class="tabular">82%</span></div><div class="card-row"><span>Last run</span><span class="dim">12d ago · test</span></div></div>
        <div class="card col-4"><div class="card-head"><div class="card-title">Yesterday vs today</div><span class="dim tabular">+12%</span></div><div class="card-row"><span>Solar (kWh)</span><span class="tabular">28.4 vs 25.3</span></div><div class="card-row"><span>Cost ($)</span><span class="tabular">4.82 vs 4.31</span></div></div>
      </div>
    </section>

    <!-- ====================================================
         TAB: HVAC
         ==================================================== -->
`,Um=`    <section class="tab" data-tab="hvac">
      <header class="page-header">
        <div>
          <h1 class="page-title">HVAC</h1>
          <div class="page-subtitle">5 zones · cool mode · system demand 64%</div>
        </div>
        <div class="page-actions">
          <span class="badge green lg">comfort 92%</span>
        </div>
      </header>

      <!-- CONTROLS BAR — HVAC coordinator knobs (this tab was light on knobs in P1 v1) -->
      <div class="controls-bar">
        <div class="knob span-3">
          <div class="knob-label">System mode</div>
          <div class="pill-group" style="width:100%">
            <button class="active" style="flex:1">Cool</button>
            <button style="flex:1">Heat</button>
            <button style="flex:1">Auto</button>
            <button style="flex:1">Off</button>
          </div>
          <div class="card-sub">Override per-zone in cards below</div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">House setpoint</div>
          <div class="row" style="gap:var(--space-xs); align-items:center">
            <button class="btn icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button>
            <div class="knob-value tabular" style="flex:1; text-align:center">72°</div>
            <button class="btn icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button>
          </div>
          <div class="card-sub">All zones · individual offsets retained</div>
        </div>
        <div class="knob span-3">
          <div class="knob-label">Pre-cool aggressiveness <span class="badge accent">URA</span></div>
          <div class="knob-value">Balanced</div>
          <div class="knob-action">
            <input type="range" min="0" max="3" value="2" class="slider">
          </div>
          <div class="card-sub">Passive · Conservative · <strong>Balanced</strong> · Aggressive</div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Coast threshold</div>
          <div class="knob-value tabular">45 <span class="dim" style="font-weight:400; font-size:var(--text-sm)">min</span></div>
          <div class="knob-action">
            <input type="range" min="15" max="120" value="45" class="slider">
          </div>
          <div class="card-sub">Predicted-vacancy lookahead</div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">URA modes</div>
          <div class="card-row"><span style="font-size:var(--text-xs)">Arrester</span><label class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></label></div>
          <div class="card-row"><span style="font-size:var(--text-xs)">Observation</span><label class="toggle"><input type="checkbox"><span class="toggle-slot"></span></label></div>
          <div class="card-row"><span style="font-size:var(--text-xs)">Pre-cool</span><label class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></label></div>
        </div>
      </div>

      <!-- House aggregate -->
      <div class="grid">
        <div class="card col-3">
          <div class="card-title">House avg</div>
          <div class="card-value tabular">73°<span class="card-unit">F</span></div>
          <div class="card-sub">range 71° – 76° · outside 64°</div>
        </div>
        <div class="card col-3">
          <div class="card-title">System demand</div>
          <div class="card-value tabular">64<span class="card-unit">%</span></div>
          <div class="gauge-track"><div class="gauge-fill orange" style="width:64%"></div></div>
        </div>
        <div class="card col-3">
          <div class="card-title">Today runtime</div>
          <div class="card-value tabular">4.2<span class="card-unit">h</span></div>
          <div class="card-sub">est. cost: $2.18 · 6.4 kWh</div>
        </div>
        <div class="card col-3 status-blue">
          <div class="card-title"><svg class="icon-sm"><use href="#lc-sparkles"/></svg>URA intent</div>
          <div class="row" style="gap:var(--space-xs); margin-top:var(--space-xs)">
            <span class="badge blue">pre-cool Kids</span>
            <span class="badge yellow">coast Master</span>
          </div>
          <div class="card-sub">Solar surplus → push cooling forward</div>
        </div>
      </div>

      <!-- Zone cards -->
      <div class="section-head">
        <h2>Zones</h2>
      </div>
      <div class="grid">
        <!-- Main Living -->
        <div class="card col-4">
          <div class="card-head">
            <div class="row" style="gap:var(--space-xs)"><span class="dot green"></span><strong>Main Living</strong></div>
            <span class="badge green">normal</span>
          </div>
          <div class="row" style="gap:var(--space-md); padding:var(--space-xs) 0; align-items:flex-start">
            <div>
              <div class="card-value tabular">72°</div>
              <div class="card-sub">current</div>
            </div>
            <div style="flex:1; text-align:right">
              <div class="card-value sm tabular">72°</div>
              <div class="card-sub">target · cool</div>
            </div>
          </div>
          <div class="card-row"><span>Action</span><span><span class="badge accent">cooling</span></span></div>
          <div class="card-row"><span>Demand</span><span class="tabular">42%</span></div>
          <div class="card-row"><span>Comfort</span><span class="tabular" style="color:var(--status-green)">95%</span></div>
          <div class="card-row"><span>Thermostat</span><span class="dim">Nest · Great Room</span></div>
          <div class="card-controls">
            <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button>
            <span class="tabular" style="font-size:var(--text-md); font-weight:600; align-self:center; padding:0 4px">72°</span>
            <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button>
            <div class="pill-group" style="margin-left:auto">
              <button class="active">Cool</button>
              <button>Heat</button>
              <button>Auto</button>
            </div>
          </div>
        </div>

        <!-- Master Suite -->
        <div class="card col-4 status-yellow">
          <div class="card-head">
            <div class="row" style="gap:var(--space-xs)"><span class="dot yellow"></span><strong>Master Suite</strong></div>
            <span class="badge yellow">coast</span>
          </div>
          <div class="row" style="gap:var(--space-md); padding:var(--space-xs) 0; align-items:flex-start">
            <div>
              <div class="card-value tabular">74°</div>
              <div class="card-sub">current</div>
            </div>
            <div style="flex:1; text-align:right">
              <div class="card-value sm tabular">73°</div>
              <div class="card-sub">target · cool</div>
            </div>
          </div>
          <div class="card-row"><span>Action</span><span><span class="badge">idle (coasting)</span></span></div>
          <div class="card-row"><span>Demand</span><span class="tabular">18%</span></div>
          <div class="card-row"><span>Comfort</span><span class="tabular" style="color:var(--status-yellow)">88%</span></div>
          <div class="card-row"><span>URA reason</span><span class="dim">occupied drop in 45m</span></div>
          <div class="card-controls">
            <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button>
            <span class="tabular" style="font-size:var(--text-md); font-weight:600; align-self:center; padding:0 4px">73°</span>
            <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button>
            <div class="pill-group" style="margin-left:auto">
              <button class="active">Cool</button>
              <button>Heat</button>
              <button>Auto</button>
            </div>
          </div>
        </div>

        <!-- Kids -->
        <div class="card col-4 status-blue">
          <div class="card-head">
            <div class="row" style="gap:var(--space-xs)"><span class="dot blue"></span><strong>Kids</strong></div>
            <span class="badge blue">pre-cool</span>
          </div>
          <div class="row" style="gap:var(--space-md); padding:var(--space-xs) 0; align-items:flex-start">
            <div>
              <div class="card-value tabular">71°</div>
              <div class="card-sub">current</div>
            </div>
            <div style="flex:1; text-align:right">
              <div class="card-value sm tabular">71°</div>
              <div class="card-sub">target · pre-cool</div>
            </div>
          </div>
          <div class="card-row"><span>Action</span><span><span class="badge accent">cooling hard</span></span></div>
          <div class="card-row"><span>Demand</span><span class="tabular">88%</span></div>
          <div class="card-row"><span>Comfort</span><span class="tabular" style="color:var(--status-green)">93%</span></div>
          <div class="card-row"><span>URA reason</span><span class="dim">Ziri bedtime 19:30</span></div>
          <div class="card-controls">
            <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-minus"/></svg></button>
            <span class="tabular" style="font-size:var(--text-md); font-weight:600; align-self:center; padding:0 4px">71°</span>
            <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-plus"/></svg></button>
            <div class="pill-group" style="margin-left:auto">
              <button class="active">Cool</button>
              <button>Heat</button>
              <button>Auto</button>
            </div>
          </div>
        </div>

        <!-- Guest -->
        <div class="card col-6">
          <div class="card-head">
            <div class="row" style="gap:var(--space-xs)"><span class="dot grey"></span><strong>Guest Suite</strong></div>
            <span class="badge">setback</span>
          </div>
          <div class="row" style="gap:var(--space-md); padding:var(--space-xs) 0">
            <div><div class="card-value sm tabular">76°</div><div class="card-sub">current</div></div>
            <div style="flex:1; text-align:right"><div class="card-value sm tabular">78°</div><div class="card-sub">target · cool</div></div>
          </div>
          <div class="card-row"><span>Action</span><span class="dim">unoccupied · 6h</span></div>
          <div class="card-row"><span>URA</span><span class="dim">guest mode off · vacancy economy</span></div>
        </div>

        <!-- Hazard guard + advanced URA knobs -->
        <div class="card col-6">
          <div class="card-head">
            <div class="card-title"><svg class="icon-sm"><use href="#lc-alert"/></svg>Hazard guard &amp; advanced</div>
            <span class="badge green">guarding</span>
          </div>
          <div class="card-row"><span>Hot-zone temp limit</span><span class="tabular">82°F</span></div>
          <div class="card-row"><span>Cold-zone temp limit</span><span class="tabular">62°F</span></div>
          <div class="card-row"><span>Comfort weight (mode)</span><span class="dim">balanced · energy 0.4 · comfort 0.6</span></div>
          <div class="card-row"><span>Setback economy (vacancy)</span><span><span class="badge green">active 6h+</span></span></div>
          <div class="card-row"><span>Routine awareness influence</span><span class="tabular">strong</span></div>
          <div class="card-row"><span>Min daily HVAC severity</span><span><span class="badge accent">ALERT (3)</span></span></div>
          <div class="card-sub" style="margin-top:var(--space-xs)">Hazard guard ignores arrester to force cooling when zones exceed limit. Severity gates anomaly emit.</div>
        </div>
      </div>
    </section>

    <!-- ====================================================
         TAB: PRESENCE
         ==================================================== -->
`,km=`    <section class="tab" data-tab="presence">
      <header class="page-header">
        <div>
          <h1 class="page-title">Presence</h1>
          <div class="page-subtitle">Fusion: BLE + cameras + motion + radar · 4 people · 3 home</div>
        </div>
        <div class="page-actions">
          <span class="badge green lg">3 / 4 home · 14 events/5min</span>
        </div>
      </header>

      <!-- CONTROLS BAR — presence coordinator knobs -->
      <div class="controls-bar">
        <div class="knob span-3">
          <div class="knob-label">Music following <span class="badge green">3 rooms</span></div>
          <div class="row" style="gap:var(--space-sm)"><label class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></label><span class="dim" style="font-size:var(--text-sm)">master enable</span></div>
          <div class="knob-action">
            <button class="btn sm">Per-room <svg class="icon-sm"><use href="#lc-chevron-down"/></svg></button>
          </div>
        </div>
        <div class="knob span-3">
          <div class="knob-label">BLE confidence floor</div>
          <div class="knob-value tabular">75 <span class="dim" style="font-weight:400; font-size:var(--text-sm)">% · -60 dBm</span></div>
          <div class="knob-action">
            <input type="range" min="40" max="95" value="75" class="slider">
          </div>
          <div class="card-sub">Below this, ignore BLE alone (require fusion)</div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Transition smoothing</div>
          <div class="knob-value tabular">8 <span class="dim" style="font-weight:400; font-size:var(--text-sm)">sec</span></div>
          <div class="knob-action">
            <input type="range" min="0" max="30" value="8" class="slider">
          </div>
          <div class="card-sub">Debounce window for room change</div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Census mode</div>
          <div class="pill-group" style="width:100%">
            <button style="flex:1">Strict</button>
            <button class="active" style="flex:1">Lenient</button>
          </div>
          <div class="card-sub">Lenient keeps known-present 5m</div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Auto-detect guests</div>
          <div class="row" style="gap:var(--space-sm)"><label class="toggle"><input type="checkbox"><span class="toggle-slot"></span></label><span class="dim" style="font-size:var(--text-sm)">camera-only</span></div>
          <div class="card-sub">Unknown faces → guest count</div>
        </div>
      </div>

      <!-- Person cards with fusion -->
      <div class="grid">
        <div class="card col-3 status-green">
          <div class="row" style="gap:var(--space-sm)">
            <div style="width:48px;height:48px;border-radius:var(--radius-full);background:linear-gradient(135deg,#42A5F5,#1E88E5);display:flex;align-items:center;justify-content:center;font-weight:600;font-size:var(--text-lg);color:white">O</div>
            <div style="flex:1; min-width:0">
              <div style="font-weight:600; color:var(--text-secondary); font-size:var(--text-sm)">Oji</div>
              <div style="font-weight:700; font-size:var(--text-lg); color:var(--status-green); line-height:1.1; margin-top:2px">Office <span class="dim" style="font-weight:400; font-size:var(--text-sm)">· 18m</span></div>
            </div>
            <span class="dot green live"></span>
          </div>
          <div class="card-row"><span>Fusion confidence</span><span><strong class="tabular">92%</strong></span></div>
          <div class="card-row"><span>Sources</span><span class="dim">BLE + motion + camera</span></div>
          <div class="card-row"><span>Likely next</span><span><span class="badge accent">Master Bed</span> 22:15</span></div>
          <div class="card-controls">
            <button class="btn sm">Override location <svg class="icon-sm"><use href="#lc-chevron-down"/></svg></button>
          </div>
        </div>
        <div class="card col-3 status-green">
          <div class="row" style="gap:var(--space-sm)">
            <div style="width:48px;height:48px;border-radius:var(--radius-full);background:linear-gradient(135deg,#EC407A,#C2185B);display:flex;align-items:center;justify-content:center;font-weight:600;font-size:var(--text-lg);color:white">E</div>
            <div style="flex:1">
              <div style="font-weight:600; color:var(--text-secondary); font-size:var(--text-sm)">Ezinne</div>
              <div style="font-weight:700; font-size:var(--text-lg); color:var(--status-green); line-height:1.1; margin-top:2px">Kitchen <span class="dim" style="font-weight:400; font-size:var(--text-sm)">· 6m</span></div>
            </div>
            <span class="dot green live"></span>
          </div>
          <div class="card-row"><span>Fusion confidence</span><span><strong class="tabular">88%</strong></span></div>
          <div class="card-row"><span>Sources</span><span class="dim">camera + motion</span></div>
          <div class="card-row"><span>Likely next</span><span><span class="badge accent">Great Room</span> 19:10</span></div>
          <div class="card-controls">
            <button class="btn sm">Override location <svg class="icon-sm"><use href="#lc-chevron-down"/></svg></button>
          </div>
        </div>
        <div class="card col-3 status-yellow">
          <div class="row" style="gap:var(--space-sm)">
            <div style="width:48px;height:48px;border-radius:var(--radius-full);background:linear-gradient(135deg,#66BB6A,#388E3C);display:flex;align-items:center;justify-content:center;font-weight:600;font-size:var(--text-lg);color:white">J</div>
            <div style="flex:1">
              <div style="font-weight:600; color:var(--text-secondary); font-size:var(--text-sm)">Jaya</div>
              <div style="font-weight:700; font-size:var(--text-lg); color:var(--status-yellow); line-height:1.1; margin-top:2px">Away <span class="dim" style="font-weight:400; font-size:var(--text-sm)">· since 16:12</span></div>
            </div>
            <span class="dot yellow"></span>
          </div>
          <div class="card-row"><span>Last seen</span><span><span class="dim">BLE: not_home</span></span></div>
          <div class="card-row"><span>ETA home</span><span class="tabular">~19:30</span></div>
          <div class="card-row"><span>Arrival routine</span><span><span class="badge green">armed</span></span></div>
          <div class="card-controls">
            <button class="btn sm">Mark home</button>
            <button class="btn sm">Mark away</button>
          </div>
        </div>
        <div class="card col-3 status-green">
          <div class="row" style="gap:var(--space-sm)">
            <div style="width:48px;height:48px;border-radius:var(--radius-full);background:linear-gradient(135deg,#FFA726,#F57C00);display:flex;align-items:center;justify-content:center;font-weight:600;font-size:var(--text-lg);color:white">Z</div>
            <div style="flex:1">
              <div style="font-weight:600; color:var(--text-secondary); font-size:var(--text-sm)">Ziri</div>
              <div style="font-weight:700; font-size:var(--text-lg); color:var(--status-green); line-height:1.1; margin-top:2px">Playroom <span class="dim" style="font-weight:400; font-size:var(--text-sm)">· 24m</span></div>
            </div>
            <span class="dot green live"></span>
          </div>
          <div class="card-row"><span>Fusion confidence</span><span><strong class="tabular">95%</strong></span></div>
          <div class="card-row"><span>Sources</span><span class="dim">motion + radar</span></div>
          <div class="card-row"><span>Bedtime routine</span><span><span class="badge blue">in 43m</span></span></div>
          <div class="card-controls">
            <button class="btn sm">Override location <svg class="icon-sm"><use href="#lc-chevron-down"/></svg></button>
          </div>
        </div>
      </div>

      <!-- Aggregates -->
      <div class="section-head"><h2>House aggregates</h2></div>
      <div class="grid">
        <div class="card col-3">
          <div class="card-title">Property count</div>
          <div class="card-value tabular">3</div>
          <div class="card-sub">all inside · 0 in outdoor rooms</div>
        </div>
        <div class="card col-3">
          <div class="card-title">Census today</div>
          <div class="card-value tabular">3</div>
          <div class="card-sub">peak: 4 at 14:30 · min: 1 at 10:15</div>
        </div>
        <div class="card col-3">
          <div class="card-title">Transitions today</div>
          <div class="card-value tabular">47</div>
          <div class="card-sub"><span class="badge yellow">z=2.4</span> ADVISORY anomaly</div>
        </div>
        <div class="card col-3 status-blue">
          <div class="card-title"><svg class="icon-sm"><use href="#lc-sparkles"/></svg>Routine awareness</div>
          <div class="card-row"><span>Next state</span><span><strong>home_night</strong> 21:30</span></div>
          <div class="card-row"><span>Confidence</span><span class="tabular">87%</span></div>
        </div>
      </div>

      <!-- Source fusion -->
      <div class="section-head"><h2>Detection sources</h2></div>
      <div class="grid">
        <div class="card col-4">
          <div class="card-head">
            <div class="card-title"><svg class="icon-sm"><use href="#lc-radio"/></svg>BLE (Bermuda)</div>
            <span class="badge green">3 active</span>
          </div>
          <div class="card-row"><span>Oji iPhone</span><span><span class="badge green">Office</span> -52 dBm</span></div>
          <div class="card-row"><span>Ezinne iPhone</span><span><span class="badge green">Kitchen</span> -61 dBm</span></div>
          <div class="card-row"><span>Ziri Watch</span><span><span class="badge green">Playroom</span> -48 dBm</span></div>
          <div class="card-row"><span>Jaya iPhone</span><span><span class="dim">not_home · 16:12</span></span></div>
        </div>
        <div class="card col-4">
          <div class="card-head">
            <div class="card-title"><svg class="icon-sm"><use href="#lc-video"/></svg>Cameras (detection)</div>
            <span class="badge green">9 streaming</span>
          </div>
          <div class="card-row"><span>Kitchen cam</span><span class="dim">person 16s ago</span></div>
          <div class="card-row"><span>Great Room cam</span><span class="dim">person 2m ago</span></div>
          <div class="card-row"><span>Front porch</span><span class="dim">vehicle 4m ago</span></div>
          <div class="card-row"><span>Back deck</span><span class="dim">cat 12m ago</span></div>
        </div>
        <div class="card col-4">
          <div class="card-head">
            <div class="card-title"><svg class="icon-sm"><use href="#lc-eye"/></svg>Motion + radar</div>
            <span class="badge green">14 events / 5m</span>
          </div>
          <div class="card-row"><span>Office radar</span><span><span class="badge green">person stationary</span></span></div>
          <div class="card-row"><span>Playroom motion</span><span><span class="badge green">active</span></span></div>
          <div class="card-row"><span>Kitchen motion</span><span><span class="badge green">active</span></span></div>
          <div class="card-row"><span>Master Bath</span><span class="dim">idle 38m</span></div>
        </div>
      </div>

      <!-- Controls bottom -->
      <div class="section-head"><h2>Music following</h2></div>
      <div class="grid">
        <div class="card col-12">
          <div class="card-head">
            <div class="card-title"><svg class="icon-sm"><use href="#lc-music"/></svg>Per-room enablement</div>
            <span class="badge green">enabled in 3 rooms · 12 transitions today</span>
          </div>
          <div class="grid gap-sm" style="grid-template-columns:repeat(auto-fill,minmax(180px,1fr))">
            <div class="card-row"><span>Master Bed</span><label class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></label></div>
            <div class="card-row"><span>Office</span><label class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></label></div>
            <div class="card-row"><span>Kitchen</span><label class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></label></div>
            <div class="card-row"><span>Great Room</span><label class="toggle"><input type="checkbox"><span class="toggle-slot"></span></label></div>
            <div class="card-row"><span>Playroom</span><label class="toggle"><input type="checkbox"><span class="toggle-slot"></span></label></div>
            <div class="card-row"><span>Gym</span><label class="toggle"><input type="checkbox"><span class="toggle-slot"></span></label></div>
          </div>
        </div>
      </div>
    </section>

    <!-- ====================================================
         TAB: SECURITY
         ==================================================== -->
`,Cm=`    <section class="tab" data-tab="security">
      <header class="page-header">
        <div>
          <h1 class="page-title">Security</h1>
          <div class="page-subtitle">Disarmed · 4/4 locks · 9 cameras streaming</div>
        </div>
        <div class="page-actions">
          <button class="btn"><svg class="icon"><use href="#lc-bell"/></svg> Events</button>
        </div>
      </header>

      <!-- CONTROLS BAR — security coordinator knobs -->
      <div class="controls-bar">
        <div class="knob span-4">
          <div class="knob-label">Alarm mode <span class="badge green">URA: disarmed @ home_evening</span></div>
          <div class="pill-group" style="width:100%">
            <button class="active" style="flex:1">Off</button>
            <button style="flex:1">Home</button>
            <button style="flex:1">Night</button>
            <button class="" style="flex:1">Away</button>
          </div>
          <div class="card-sub">Arm requires 5s hold confirm</div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Auto-arm on leave</div>
          <div class="row" style="gap:var(--space-sm)"><label class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></label><span class="dim" style="font-size:var(--text-sm)">2m delay</span></div>
          <div class="card-sub">When census drops to 0</div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Auto-arm at sleep</div>
          <div class="row" style="gap:var(--space-sm)"><label class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></label><span class="dim" style="font-size:var(--text-sm)">→ Night</span></div>
          <div class="card-sub">Triggers on house_state=sleep</div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Lock-after-motion</div>
          <div class="knob-value tabular">5 <span class="dim" style="font-weight:400; font-size:var(--text-sm)">min</span></div>
          <div class="knob-action">
            <input type="range" min="0" max="30" value="5" class="slider">
          </div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Camera privacy</div>
          <div class="row" style="gap:var(--space-sm)"><label class="toggle"><input type="checkbox"><span class="toggle-slot"></span></label><span class="dim" style="font-size:var(--text-sm)">all off</span></div>
          <div class="card-sub">Indoor cams · obscure when home_evening</div>
        </div>
      </div>

      <!-- Hero KPI -->
      <div class="grid">
        <div class="card col-3 status-green">
          <div class="card-title"><svg class="icon-sm"><use href="#lc-shield"/></svg>Alarm</div>
          <div class="card-value sm">Disarmed</div>
          <div class="card-sub">last armed 23:00 yesterday</div>
        </div>
        <div class="card col-3 status-green">
          <div class="card-title"><svg class="icon-sm"><use href="#lc-lock"/></svg>Locks</div>
          <div class="card-value tabular">4 / 4</div>
          <div class="card-sub">all locked</div>
        </div>
        <div class="card col-3 status-green">
          <div class="card-title"><svg class="icon-sm"><use href="#lc-video"/></svg>Cameras</div>
          <div class="card-value tabular">9 / 9</div>
          <div class="card-sub">streaming · 2 with motion</div>
        </div>
        <div class="card col-3 status-yellow">
          <div class="card-title"><svg class="icon-sm"><use href="#lc-bell"/></svg>Recent events</div>
          <div class="card-value tabular">3</div>
          <div class="card-sub">last: garage opened 17:54</div>
        </div>
      </div>

      <!-- Cameras grouped -->
      <div class="section-head"><h2>Cameras · entryways</h2></div>
      <div class="grid">
        <div class="card col-4">
          <div style="aspect-ratio:16/9; background:linear-gradient(135deg,#1a1a2e,#0f0f1f); border-radius:var(--radius-md); display:flex; align-items:center; justify-content:center; color:var(--text-tertiary); margin-bottom:var(--space-xs); position:relative">
            <svg class="icon-xl"><use href="#lc-video"/></svg>
            <span class="badge red" style="position:absolute; top:8px; left:8px"><span class="dot red live" style="background:white"></span>REC</span>
          </div>
          <div class="row between"><strong>Front Door</strong><span class="badge yellow">motion 2m</span></div>
          <div class="card-sub">vehicle detected · Jaya commute?</div>
        </div>
        <div class="card col-4">
          <div style="aspect-ratio:16/9; background:linear-gradient(135deg,#1a1a2e,#0f0f1f); border-radius:var(--radius-md); display:flex; align-items:center; justify-content:center; color:var(--text-tertiary); margin-bottom:var(--space-xs); position:relative">
            <svg class="icon-xl"><use href="#lc-video"/></svg>
            <span class="badge red" style="position:absolute; top:8px; left:8px"><span class="dot red live" style="background:white"></span>REC</span>
          </div>
          <div class="row between"><strong>Garage</strong><span class="badge">idle</span></div>
          <div class="card-sub">door state: closed · 53m</div>
        </div>
        <div class="card col-4">
          <div style="aspect-ratio:16/9; background:linear-gradient(135deg,#1a1a2e,#0f0f1f); border-radius:var(--radius-md); display:flex; align-items:center; justify-content:center; color:var(--text-tertiary); margin-bottom:var(--space-xs); position:relative">
            <svg class="icon-xl"><use href="#lc-video"/></svg>
            <span class="badge red" style="position:absolute; top:8px; left:8px"><span class="dot red live" style="background:white"></span>REC</span>
          </div>
          <div class="row between"><strong>Back Door</strong><span class="badge">idle</span></div>
          <div class="card-sub">no events 4h</div>
        </div>
      </div>

      <div class="section-head"><h2>Cameras · outside</h2></div>
      <div class="grid">
        <div class="card col-3">
          <div style="aspect-ratio:16/9; background:linear-gradient(135deg,#1a1a2e,#0f0f1f); border-radius:var(--radius-md); margin-bottom:var(--space-xs); display:flex; align-items:center; justify-content:center"><svg class="icon-lg"><use href="#lc-video"/></svg></div>
          <div class="row between"><strong>Driveway</strong><span class="dim">streaming</span></div>
        </div>
        <div class="card col-3">
          <div style="aspect-ratio:16/9; background:linear-gradient(135deg,#1a1a2e,#0f0f1f); border-radius:var(--radius-md); margin-bottom:var(--space-xs); display:flex; align-items:center; justify-content:center"><svg class="icon-lg"><use href="#lc-video"/></svg></div>
          <div class="row between"><strong>Side Yard</strong><span class="dim">streaming</span></div>
        </div>
        <div class="card col-3">
          <div style="aspect-ratio:16/9; background:linear-gradient(135deg,#1a1a2e,#0f0f1f); border-radius:var(--radius-md); margin-bottom:var(--space-xs); display:flex; align-items:center; justify-content:center"><svg class="icon-lg"><use href="#lc-video"/></svg></div>
          <div class="row between"><strong>Back Deck</strong><span class="badge yellow">cat 12m</span></div>
        </div>
        <div class="card col-3">
          <div style="aspect-ratio:16/9; background:linear-gradient(135deg,#1a1a2e,#0f0f1f); border-radius:var(--radius-md); margin-bottom:var(--space-xs); display:flex; align-items:center; justify-content:center"><svg class="icon-lg"><use href="#lc-video"/></svg></div>
          <div class="row between"><strong>Pool</strong><span class="dim">streaming</span></div>
        </div>
      </div>

      <div class="section-head"><h2>Cameras · inside</h2></div>
      <div class="grid">
        <div class="card col-3">
          <div style="aspect-ratio:16/9; background:linear-gradient(135deg,#1a1a2e,#0f0f1f); border-radius:var(--radius-md); margin-bottom:var(--space-xs); display:flex; align-items:center; justify-content:center"><svg class="icon-lg"><use href="#lc-video"/></svg></div>
          <div class="row between"><strong>Great Room</strong><span class="badge green">person 2m</span></div>
        </div>
        <div class="card col-3">
          <div style="aspect-ratio:16/9; background:linear-gradient(135deg,#1a1a2e,#0f0f1f); border-radius:var(--radius-md); margin-bottom:var(--space-xs); display:flex; align-items:center; justify-content:center"><svg class="icon-lg"><use href="#lc-video"/></svg></div>
          <div class="row between"><strong>Kitchen</strong><span class="badge green">person 16s</span></div>
        </div>
      </div>

      <!-- Locks + contact sensors -->
      <div class="section-head"><h2>Locks &amp; entries</h2></div>
      <div class="grid">
        <div class="card col-3 status-green">
          <div class="card-head">
            <div class="row" style="gap:var(--space-xs)"><svg class="icon-sm" style="color:var(--status-green)"><use href="#lc-lock"/></svg><strong>Front Door</strong></div>
            <span class="badge green">locked</span>
          </div>
          <div class="card-sub">last: 16:38 · auto-lock 5m</div>
          <div class="card-controls">
            <button class="btn sm danger" data-confirm>Unlock <svg class="icon-sm"><use href="#lc-chevron-right"/></svg></button>
          </div>
        </div>
        <div class="card col-3 status-green">
          <div class="card-head">
            <div class="row" style="gap:var(--space-xs)"><svg class="icon-sm" style="color:var(--status-green)"><use href="#lc-lock"/></svg><strong>Back Door</strong></div>
            <span class="badge green">locked</span>
          </div>
          <div class="card-sub">last: 14:22</div>
          <div class="card-controls"><button class="btn sm danger" data-confirm>Unlock</button></div>
        </div>
        <div class="card col-3 status-green">
          <div class="card-head">
            <div class="row" style="gap:var(--space-xs)"><svg class="icon-sm" style="color:var(--status-green)"><use href="#lc-lock"/></svg><strong>Garage</strong></div>
            <span class="badge green">locked</span>
          </div>
          <div class="card-sub">door state: closed</div>
          <div class="card-controls"><button class="btn sm">Open</button></div>
        </div>
        <div class="card col-3 status-green">
          <div class="card-head">
            <div class="row" style="gap:var(--space-xs)"><svg class="icon-sm" style="color:var(--status-green)"><use href="#lc-lock"/></svg><strong>Side Gate</strong></div>
            <span class="badge green">locked</span>
          </div>
          <div class="card-sub">last: yesterday</div>
          <div class="card-controls"><button class="btn sm" disabled>—</button></div>
        </div>
      </div>

      <div class="section-head"><h2>Recent entry events</h2></div>
      <div class="card col-12">
        <div class="timeline">
          <div class="timeline-row"><div class="timeline-time">17:54</div><div class="timeline-body"><div class="timeline-headline">Garage door <strong>opened</strong></div><div class="timeline-reason">closed 3m later · auto-dismissed</div></div></div>
          <div class="timeline-row"><div class="timeline-time">16:38</div><div class="timeline-body"><div class="timeline-headline">Front Door <strong>locked</strong></div><div class="timeline-reason">Oji · keypad</div></div></div>
          <div class="timeline-row"><div class="timeline-time">14:22</div><div class="timeline-body"><div class="timeline-headline">Back Door <strong>locked</strong></div><div class="timeline-reason">auto · 5m after motion stopped</div></div></div>
        </div>
      </div>
    </section>

    <!-- ====================================================
         TAB: SAFETY — fed by Safety coordinator
         Hazards (fire/CO/smoke/leak/freeze/garage-open),
         detectors, auto-shutoff, emergency contacts.
         Distinct from Security (alarm/locks/cameras).
         ==================================================== -->
`,Hm=`    <section class="tab" data-tab="safety">
      <header class="page-header">
        <div>
          <h1 class="page-title">Safety</h1>
          <div class="page-subtitle">0 active hazards · 12 detectors OK · auto-shutoff armed · 3 events today (auto-dismissed)</div>
        </div>
        <div class="page-actions">
          <span class="badge green lg"><svg class="icon-sm"><use href="#lc-shield"/></svg>guarding</span>
        </div>
      </header>

      <!-- CONTROLS BAR — Safety coordinator knobs -->
      <div class="controls-bar">
        <div class="knob span-3">
          <div class="knob-label">Safety routines <span class="badge green">all armed</span></div>
          <div class="pill-group" style="width:100%">
            <button class="active" style="flex:1">All armed</button>
            <button style="flex:1">Day only</button>
            <button style="flex:1">Disabled</button>
          </div>
          <div class="card-sub">Auto-respond to fire / leak / freeze</div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Auto water shutoff <span class="badge accent">URA</span></div>
          <div class="row" style="gap:var(--space-sm)"><label class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></label><span class="dim" style="font-size:var(--text-sm)">on leak detected</span></div>
          <div class="card-sub">Triggers main valve close</div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Auto-lock on fire</div>
          <div class="row" style="gap:var(--space-sm)"><label class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></label><span class="dim" style="font-size:var(--text-sm)">unlocks all doors</span></div>
          <div class="card-sub">Egress for occupants</div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Freeze threshold</div>
          <div class="knob-value tabular">38° <span class="dim" style="font-weight:400; font-size:var(--text-sm)">F</span></div>
          <div class="knob-action"><input type="range" min="30" max="50" value="38" class="slider"></div>
          <div class="card-sub">Indoor &lt; this = WARN</div>
        </div>
        <div class="knob span-3">
          <div class="knob-label">Hazard severity floor <span class="badge accent">3</span></div>
          <div class="knob-value">WARNING <span class="badge" style="font-size:var(--text-xs)">always notify ≥</span></div>
          <div class="knob-action"><input type="range" min="0" max="4" value="2" class="slider"></div>
          <div class="card-sub">Anomaly emit threshold for Safety</div>
        </div>
      </div>

      <!-- Hero KPI -->
      <div class="grid">
        <div class="card col-3 status-green">
          <div class="card-title"><svg class="icon-sm"><use href="#lc-shield"/></svg>Active hazards</div>
          <div class="card-value tabular">0</div>
          <div class="card-sub">last 24h: 3 events, all auto-resolved</div>
        </div>
        <div class="card col-3 status-green">
          <div class="card-title"><svg class="icon-sm"><use href="#lc-check"/></svg>Detectors</div>
          <div class="card-value tabular">12 / 12</div>
          <div class="card-sub">smoke 4 · CO 3 · leak 3 · freeze 2</div>
        </div>
        <div class="card col-3 status-green">
          <div class="card-title"><svg class="icon-sm"><use href="#lc-bell"/></svg>Events today</div>
          <div class="card-value tabular">3</div>
          <div class="card-sub">all auto-dismissed in &lt; 5m</div>
        </div>
        <div class="card col-3 strong">
          <div class="card-title"><svg class="icon-sm"><use href="#lc-brain"/></svg>URA intent</div>
          <div class="card-sub" style="margin-top:var(--space-xs); font-size:var(--text-sm); color:var(--text-primary)"><span class="badge green">guarding</span> · last review 18:42</div>
          <div class="card-sub">No anomalies in detector frequency. All 12 sensors responsive.</div>
        </div>
      </div>

      <!-- Detectors by type -->
      <div class="section-head"><h2>Smoke &amp; CO</h2></div>
      <div class="grid">
        <div class="card col-3 status-green"><div class="card-head"><div class="card-title"><svg class="icon-sm"><use href="#lc-alert"/></svg>Kitchen</div><span class="badge green">clear</span></div><div class="card-row"><span>Smoke</span><span class="tabular">0 ppm</span></div><div class="card-row"><span>CO</span><span class="tabular">2 ppm</span></div><div class="card-row"><span>Battery</span><span class="tabular">92%</span></div><div class="card-row"><span>Tested</span><span class="dim">14d ago</span></div></div>
        <div class="card col-3 status-green"><div class="card-head"><div class="card-title"><svg class="icon-sm"><use href="#lc-alert"/></svg>Hallway</div><span class="badge green">clear</span></div><div class="card-row"><span>Smoke</span><span class="tabular">0 ppm</span></div><div class="card-row"><span>CO</span><span class="tabular">1 ppm</span></div><div class="card-row"><span>Battery</span><span class="tabular">88%</span></div><div class="card-row"><span>Tested</span><span class="dim">14d ago</span></div></div>
        <div class="card col-3 status-green"><div class="card-head"><div class="card-title"><svg class="icon-sm"><use href="#lc-alert"/></svg>Master Bed</div><span class="badge green">clear</span></div><div class="card-row"><span>Smoke</span><span class="tabular">0 ppm</span></div><div class="card-row"><span>CO</span><span class="tabular">2 ppm</span></div><div class="card-row"><span>Battery</span><span class="tabular">95%</span></div><div class="card-row"><span>Tested</span><span class="dim">14d ago</span></div></div>
        <div class="card col-3 status-yellow"><div class="card-head"><div class="card-title"><svg class="icon-sm"><use href="#lc-alert"/></svg>Garage</div><span class="badge yellow">low battery</span></div><div class="card-row"><span>Smoke</span><span class="tabular">0 ppm</span></div><div class="card-row"><span>CO</span><span class="tabular">4 ppm</span></div><div class="card-row"><span>Battery</span><span class="tabular" style="color:var(--status-yellow)">18%</span></div><div class="card-row"><span>Action</span><span class="dim">replace soon</span></div></div>
      </div>

      <div class="section-head"><h2>Water leak</h2></div>
      <div class="grid">
        <div class="card col-4 status-green"><div class="card-head"><div class="card-title"><svg class="icon-sm"><use href="#lc-alert"/></svg>Kitchen sink</div><span class="badge green">dry</span></div><div class="card-row"><span>Last detected</span><span class="dim">never</span></div><div class="card-row"><span>Battery</span><span class="tabular">87%</span></div></div>
        <div class="card col-4 status-green"><div class="card-head"><div class="card-title"><svg class="icon-sm"><use href="#lc-alert"/></svg>Water heater</div><span class="badge green">dry</span></div><div class="card-row"><span>Last detected</span><span class="dim">never</span></div><div class="card-row"><span>Battery</span><span class="tabular">91%</span></div></div>
        <div class="card col-4 status-green"><div class="card-head"><div class="card-title"><svg class="icon-sm"><use href="#lc-alert"/></svg>Laundry</div><span class="badge green">dry</span></div><div class="card-row"><span>Last detected</span><span class="dim">2d ago (1m, dismissed)</span></div><div class="card-row"><span>Battery</span><span class="tabular">93%</span></div></div>
      </div>

      <div class="section-head"><h2>Freeze &amp; garage</h2></div>
      <div class="grid">
        <div class="card col-3 status-green"><div class="card-head"><div class="card-title"><svg class="icon-sm"><use href="#lc-thermo"/></svg>Garage temp</div><span class="badge green">safe</span></div><div class="card-value sm tabular">62°</div><div class="card-sub">threshold: 38° · 24° margin</div></div>
        <div class="card col-3 status-green"><div class="card-head"><div class="card-title"><svg class="icon-sm"><use href="#lc-thermo"/></svg>Attic temp</div><span class="badge green">safe</span></div><div class="card-value sm tabular">84°</div><div class="card-sub">no freeze concern · summer</div></div>
        <div class="card col-3 status-green"><div class="card-head"><div class="card-title"><svg class="icon-sm"><use href="#lc-lock"/></svg>Garage door</div><span class="badge green">closed</span></div><div class="card-value sm">Closed</div><div class="card-sub">last open: 17:54 · 3m</div></div>
        <div class="card col-3 status-green"><div class="card-head"><div class="card-title"><svg class="icon-sm"><use href="#lc-lock"/></svg>Side gate</div><span class="badge green">closed</span></div><div class="card-value sm">Closed</div><div class="card-sub">last open: yesterday</div></div>
      </div>

      <!-- Recent safety events timeline -->
      <div class="section-head"><h2>Recent safety events</h2></div>
      <div class="card col-12">
        <div class="timeline">
          <div class="timeline-row">
            <div class="timeline-time">17:54</div>
            <div class="timeline-body">
              <div class="timeline-headline"><span class="badge green">resolved</span> Garage door opened</div>
              <div class="timeline-reason">closed 3m later · auto-dismissed · Oji vehicle event</div>
            </div>
            <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button>
          </div>
          <div class="timeline-row">
            <div class="timeline-time">12:18</div>
            <div class="timeline-body">
              <div class="timeline-headline"><span class="badge green">resolved</span> CO spike · Kitchen</div>
              <div class="timeline-reason">peak 8 ppm during cooking · cleared in 90s · below alert (35 ppm)</div>
            </div>
            <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button>
          </div>
          <div class="timeline-row">
            <div class="timeline-time">08:42</div>
            <div class="timeline-body">
              <div class="timeline-headline"><span class="badge green">resolved</span> Smoke detector test · Master Bed</div>
              <div class="timeline-reason">scheduled monthly self-test · all sensors responsive</div>
            </div>
            <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button>
          </div>
          <div class="timeline-row">
            <div class="timeline-time" style="color:var(--text-tertiary)">2d ago</div>
            <div class="timeline-body">
              <div class="timeline-headline"><span class="badge yellow">attention</span> Water leak · Laundry · 1m</div>
              <div class="timeline-reason">condensate overflow · auto-shutoff held · self-cleared, dismissed by Oji</div>
            </div>
            <button class="btn sm icon"><svg class="icon-sm"><use href="#lc-more"/></svg></button>
          </div>
        </div>
      </div>

      <!-- Emergency contacts -->
      <div class="section-head"><h2>Emergency response</h2></div>
      <div class="grid">
        <div class="card col-6">
          <div class="card-head">
            <div class="card-title"><svg class="icon-sm"><use href="#lc-bell"/></svg>Auto-call sequence</div>
            <label class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></label>
          </div>
          <div class="card-row"><span>1. Oji</span><span class="tabular">+1 ••• ••• 4127 · SMS+call</span></div>
          <div class="card-row"><span>2. Ezinne</span><span class="tabular">+1 ••• ••• 8203 · SMS+call</span></div>
          <div class="card-row"><span>3. 911 (auto-fail-over)</span><span><span class="badge red">on fire/CO ≥ 35 ppm</span></span></div>
          <div class="card-sub">Triggered on hazard ≥ CRITICAL or no ack in 90s</div>
        </div>
        <div class="card col-6">
          <div class="card-head">
            <div class="card-title"><svg class="icon-sm"><use href="#lc-activity"/></svg>Safety coordinator</div>
            <span class="badge green">healthy</span>
          </div>
          <div class="card-row"><span>Decisions today</span><span class="tabular">28</span></div>
          <div class="card-row"><span>Auto-dismissals (avg/day)</span><span class="tabular">5.2</span></div>
          <div class="card-row"><span>False alarms (7d)</span><span class="tabular">0</span></div>
          <div class="card-row"><span>Last self-check</span><span class="dim">18:35 · all sensors</span></div>
          <div class="card-controls">
            <button class="btn sm">Run drill</button>
            <button class="btn sm">Test alarms</button>
          </div>
        </div>
      </div>
    </section>

    <!-- ====================================================
         TAB: DIAGNOSTICS (incl. Alerts folded in)
         ==================================================== -->
`,_m=`    <section class="tab" data-tab="diagnostics">
      <header class="page-header">
        <div>
          <h1 class="page-title">Diagnostics</h1>
          <div class="page-subtitle">URA v4.6.7 · PRAGMA 467 · 5/5 coordinators · uptime 6d 14h</div>
        </div>
        <div class="page-actions">
          <button class="btn"><svg class="icon"><use href="#lc-activity"/></svg> Logs</button>
          <button class="btn"><svg class="icon"><use href="#lc-settings"/></svg> Reload</button>
        </div>
      </header>

      <!-- CONTROLS BAR — system-wide URA knobs -->
      <div class="controls-bar">
        <div class="knob span-3">
          <div class="knob-label">Anomaly floor <svg class="icon-sm dim"><use href="#lc-alert"/></svg></div>
          <div class="knob-value">ALERT <span class="badge accent">3</span></div>
          <div class="knob-action">
            <input type="range" min="0" max="4" value="3" class="slider">
          </div>
          <div class="card-sub">INFO · WARN · ADVISORY · <strong>ALERT</strong> · CRITICAL</div>
        </div>
        <div class="knob span-3">
          <div class="knob-label">Routine awareness floor</div>
          <div class="knob-value">ALERT <span class="badge accent">3</span></div>
          <div class="knob-action">
            <input type="range" min="0" max="4" value="3" class="slider">
          </div>
          <div class="card-sub">Only emit routine events ≥ this severity</div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">DB maintenance</div>
          <div class="knob-action" style="margin-top:0; flex-direction:column; align-items:stretch">
            <button class="btn sm">Run VACUUM</button>
            <button class="btn sm">Prune retention</button>
          </div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Observation mode (all)</div>
          <div class="row" style="gap:var(--space-sm)"><label class="toggle"><input type="checkbox"><span class="toggle-slot"></span></label><span class="dim" style="font-size:var(--text-sm)">URA records, no act</span></div>
        </div>
        <div class="knob span-2">
          <div class="knob-label">Telemetry</div>
          <div class="row" style="gap:var(--space-sm)"><label class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></label><span class="dim" style="font-size:var(--text-sm)">decision log</span></div>
          <div class="row" style="gap:var(--space-sm)"><label class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></label><span class="dim" style="font-size:var(--text-sm)">anomaly log</span></div>
        </div>
      </div>

      <!-- Top alerts strip (folded from old Alerts tab) -->
      <div class="grid">
        <div class="card col-12 status-red">
          <div class="card-head">
            <div class="card-title"><svg class="icon-sm"><use href="#lc-alert"/></svg>Active anomalies · 2</div>
            <div class="row" style="gap:var(--space-xs)">
              <button class="btn sm">Floor: ALERT</button>
              <button class="btn sm">Acknowledge all</button>
            </div>
          </div>
          <div class="timeline">
            <div class="timeline-row">
              <div class="timeline-time">18:31</div>
              <div class="timeline-body">
                <div class="timeline-headline"><span class="badge red">ALERT</span> HVAC · master_suite override_frequency</div>
                <div class="timeline-reason">z-score 3.2 · 6 user overrides in 24h vs baseline mean 1.4</div>
              </div>
              <button class="btn sm">Ack</button>
            </div>
            <div class="timeline-row">
              <div class="timeline-time">17:48</div>
              <div class="timeline-body">
                <div class="timeline-headline"><span class="badge yellow">ADVISORY</span> Presence · transition_count_daily</div>
                <div class="timeline-reason">z-score 2.4 · 47 transitions today vs baseline mean 28</div>
              </div>
              <button class="btn sm">Ack</button>
            </div>
          </div>
        </div>
      </div>

      <!-- Coordinator grid -->
      <div class="section-head"><h2>Coordinators</h2></div>
      <div class="grid">
        <div class="card col-4 status-green">
          <div class="card-head"><div class="card-title">Presence</div><span class="badge green">healthy</span></div>
          <div class="card-row"><span>Decisions today</span><span class="tabular">89</span></div>
          <div class="card-row"><span>Last decision</span><span class="dim">18:37 · Oji → Office</span></div>
          <div class="card-row"><span>Success rate</span><span class="tabular">98%</span></div>
          <div class="card-row"><span>Override freq</span><span class="tabular">2 / day</span></div>
          <div class="card-controls">
            <label class="row" style="gap:6px; font-size:var(--text-xs); flex:1"><span>Enabled</span><span class="spacer"></span><span class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></span></label>
            <button class="btn sm">Restart</button>
          </div>
        </div>
        <div class="card col-4 status-orange">
          <div class="card-head"><div class="card-title">HVAC</div><span class="badge orange">attention</span></div>
          <div class="card-row"><span>Decisions today</span><span class="tabular">64</span></div>
          <div class="card-row"><span>Last decision</span><span class="dim">18:42 · Master → coast</span></div>
          <div class="card-row"><span>Success rate</span><span class="tabular">94%</span></div>
          <div class="card-row"><span>Override freq</span><span class="tabular" style="color:var(--status-red)">6 / day <span class="badge red">ALERT</span></span></div>
          <div class="card-controls">
            <label class="row" style="gap:6px; font-size:var(--text-xs); flex:1"><span>Enabled</span><span class="spacer"></span><span class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></span></label>
            <button class="btn sm">Restart</button>
          </div>
        </div>
        <div class="card col-4 status-green">
          <div class="card-head"><div class="card-title">Energy</div><span class="badge green">healthy</span></div>
          <div class="card-row"><span>Decisions today</span><span class="tabular">42</span></div>
          <div class="card-row"><span>Last decision</span><span class="dim">18:30 · battery reserve 25%</span></div>
          <div class="card-row"><span>Success rate</span><span class="tabular">100%</span></div>
          <div class="card-row"><span>Override freq</span><span class="tabular">0 / day</span></div>
          <div class="card-controls">
            <label class="row" style="gap:6px; font-size:var(--text-xs); flex:1"><span>Enabled</span><span class="spacer"></span><span class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></span></label>
            <button class="btn sm">Restart</button>
          </div>
        </div>
        <div class="card col-4 status-green">
          <div class="card-head"><div class="card-title">Safety</div><span class="badge green">healthy</span></div>
          <div class="card-row"><span>Decisions today</span><span class="tabular">28</span></div>
          <div class="card-row"><span>Last decision</span><span class="dim">17:54 · Garage hazard auto-dismissed</span></div>
          <div class="card-row"><span>Active hazards</span><span class="tabular">0</span></div>
          <div class="card-row"><span>Override freq</span><span class="tabular">1 / day</span></div>
          <div class="card-controls">
            <label class="row" style="gap:6px; font-size:var(--text-xs); flex:1"><span>Enabled</span><span class="spacer"></span><span class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></span></label>
            <button class="btn sm">Restart</button>
          </div>
        </div>
        <div class="card col-4 status-green">
          <div class="card-head"><div class="card-title">Security</div><span class="badge green">healthy</span></div>
          <div class="card-row"><span>Decisions today</span><span class="tabular">24</span></div>
          <div class="card-row"><span>Last decision</span><span class="dim">16:38 · Front Door auto-lock</span></div>
          <div class="card-row"><span>Success rate</span><span class="tabular">100%</span></div>
          <div class="card-row"><span>Override freq</span><span class="tabular">0 / day</span></div>
          <div class="card-controls">
            <label class="row" style="gap:6px; font-size:var(--text-xs); flex:1"><span>Enabled</span><span class="spacer"></span><span class="toggle"><input type="checkbox" checked><span class="toggle-slot"></span></span></label>
            <button class="btn sm">Restart</button>
          </div>
        </div>
        <div class="card col-4">
          <div class="card-head"><div class="card-title">System</div><span class="badge">info</span></div>
          <div class="card-row"><span>Version</span><span class="mono">v4.6.7</span></div>
          <div class="card-row"><span>PRAGMA user_version</span><span class="tabular mono">467</span></div>
          <div class="card-row"><span>DB size</span><span class="tabular">812 MB</span></div>
          <div class="card-row"><span>Uptime</span><span class="tabular">6d 14h</span></div>
          <div class="card-row"><span>Write queue</span><span class="tabular">0 pending</span></div>
        </div>
      </div>

      <!-- Decisions stream + automation health -->
      <div class="grid" style="margin-top:var(--space-lg)">
        <div class="card col-8">
          <div class="card-head">
            <div class="card-title"><svg class="icon-sm"><use href="#lc-brain"/></svg>Decisions stream · last 30 min</div>
            <span class="badge accent">12 events</span>
          </div>
          <div class="timeline">
            <div class="timeline-row"><div class="timeline-time">18:42</div><div class="timeline-body"><div class="timeline-headline"><span class="badge accent">HVAC</span> Master Suite → <strong>coast</strong></div><div class="timeline-reason">predicted occupancy drop in 45m · holding at 73°</div></div></div>
            <div class="timeline-row"><div class="timeline-time">18:37</div><div class="timeline-body"><div class="timeline-headline"><span class="badge accent">Presence</span> Oji → <strong>Office</strong></div><div class="timeline-reason">BLE+motion fusion · 92% confidence</div></div></div>
            <div class="timeline-row"><div class="timeline-time">18:30</div><div class="timeline-body"><div class="timeline-headline"><span class="badge accent">Energy</span> Battery reserve → <strong>25%</strong></div><div class="timeline-reason">TOU peak begins 19:00 · hold capacity</div></div></div>
            <div class="timeline-row"><div class="timeline-time">18:24</div><div class="timeline-body"><div class="timeline-headline"><span class="badge accent">Music</span> Master Bed following → <strong>enabled</strong></div><div class="timeline-reason">Oji arrival predicted in 12m</div></div></div>
            <div class="timeline-row"><div class="timeline-time">18:15</div><div class="timeline-body"><div class="timeline-headline"><span class="badge accent">HVAC</span> Kids → <strong>pre-cool</strong></div><div class="timeline-reason">Ziri bedtime 19:30 · pull 1° below target</div></div></div>
            <div class="timeline-row"><div class="timeline-time">18:02</div><div class="timeline-body"><div class="timeline-headline"><span class="badge accent">Safety</span> Garage hazard <strong>cleared</strong></div><div class="timeline-reason">door closed 3m after open · auto-dismissed</div></div></div>
          </div>
        </div>

        <div class="card col-4">
          <div class="card-head"><div class="card-title">Automation health</div><span class="badge green">98% / 7d</span></div>
          <div class="card-row"><span>Runs today</span><span class="tabular">247 / 251 ✓</span></div>
          <div class="card-row"><span>Failed</span><span class="tabular" style="color:var(--status-red)">4</span></div>
          <div class="card-row"><span>Last error</span><span class="dim">14:22 · WhatsApp bridge timeout</span></div>
          <div class="card-row"><span>Avg exec</span><span class="tabular">84 ms</span></div>
          <div class="card-row"><span>P95 exec</span><span class="tabular">312 ms</span></div>
          <div class="card-controls">
            <button class="btn sm">View logs</button>
          </div>
        </div>
      </div>
    </section>

  </main>
</div>

<script src="shared.js"><\/script>
</body>
`,Nm={home:Mm,house:Em,zones:Om,rooms:Dm,energy:Bm,hvac:Um,presence:km,security:Cm,safety:Hm,diagnostics:_m};function Rm(){return E.jsx("div",{dangerouslySetInnerHTML:{__html:Tm}})}function jm({active:S}){return E.jsx("div",{dangerouslySetInnerHTML:{__html:Nm[S]}})}function br(){const[S,D]=fl.useState("home");return E.jsxs(E.Fragment,{children:[E.jsx(Rm,{}),E.jsx(wm,{active:S,onChange:D,children:E.jsx(jm,{active:S})})]})}function uu(){return E.jsx("style",{children:`
      /* -- CSS Reset + Base -- */
      *, *::before, *::after {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
      }

      html {
        -webkit-text-size-adjust: 100%;
        touch-action: manipulation;
      }

      /* v5.0 D1: body font-family + color + background owned by p6-shared.css
         (body.light overrides for P6). Keep only the safe defaults here. */
      body {
        overflow-x: hidden;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
      }

      #root {
        min-height: 100dvh;
      }

      /* -- Focus Visible -- */
      :focus-visible {
        outline: 2px solid #82B1FF;
        outline-offset: 2px;
        border-radius: 4px;
      }

      :focus:not(:focus-visible) {
        outline: none;
      }

      /* -- Reduced Motion -- */
      @media (prefers-reduced-motion: reduce) {
        *, *::before, *::after {
          animation-duration: 0.01ms !important;
          animation-iteration-count: 1 !important;
          transition-duration: 0.01ms !important;
        }
      }

      /* -- Scrollbar -- */
      ::-webkit-scrollbar {
        width: 4px;
        height: 4px;
      }
      ::-webkit-scrollbar-track {
        background: transparent;
      }
      ::-webkit-scrollbar-thumb {
        background: rgba(255, 255, 255, 0.12);
        border-radius: 2px;
      }
      ::-webkit-scrollbar-thumb:hover {
        background: rgba(255, 255, 255, 0.2);
      }

      /* -- Tabular Figures for data -- */
      .tabular {
        font-variant-numeric: tabular-nums;
        font-feature-settings: 'tnum';
      }

      /* -- Keyframe animations -- */
      @keyframes pulse-glow {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
      }

      @keyframes spin {
        to { transform: rotate(360deg); }
      }

      @keyframes fade-in {
        from { opacity: 0; transform: translateY(4px); }
        to { opacity: 1; transform: translateY(0); }
      }

      @keyframes shimmer {
        0% { background-position: -200% 0; }
        100% { background-position: 200% 0; }
      }

      .animate-pulse-glow {
        animation: pulse-glow 2s ease-in-out infinite;
      }

      .animate-spin {
        animation: spin 1s linear infinite;
      }

      .animate-fade-in {
        animation: fade-in 200ms ease-out;
      }
    `})}const du={text:{secondary:"rgba(255, 255, 255, 0.72)"},accent:{primary:"#82B1FF"},glass:{border:"rgba(255, 255, 255, 0.08)"}},hr={family:"-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, sans-serif",size:{md:"0.95rem"}};function qm(){const[S,D]=fl.useState(null),N=new URLSearchParams(window.location.search).has("dev");return fl.useEffect(()=>{const f=U=>{var C;if(U.origin===window.location.origin&&((C=U.data)==null?void 0:C.type)==="ura-auth"&&U.data.hassUrl){const Sa={hassUrl:U.data.hassUrl,access_token:U.data.access_token,token_type:U.data.token_type,expires:Date.now()+18e5,clientId:"",expires_in:1800,refresh_token:""};try{localStorage.setItem("hassTokens",JSON.stringify(Sa))}catch{}D(U.data.hassUrl)}};return window.addEventListener("message",f),()=>window.removeEventListener("message",f)},[]),N?E.jsxs(E.Fragment,{children:[E.jsx(uu,{}),E.jsx(br,{})]}):S?E.jsxs(Pp,{hassUrl:S,children:[E.jsx(uu,{}),E.jsx(br,{})]}):E.jsxs(E.Fragment,{children:[E.jsx(uu,{}),E.jsx("div",{style:{display:"flex",alignItems:"center",justifyContent:"center",height:"100dvh",color:du.text.secondary,fontSize:hr.size.md,fontFamily:hr.family,background:"#060612"},children:E.jsxs("div",{style:{textAlign:"center"},children:[E.jsx("div",{className:"animate-spin",style:{width:24,height:24,border:`2px solid ${du.glass.border}`,borderTop:`2px solid ${du.accent.primary}`,borderRadius:"50%",margin:"0 auto 12px"}}),"Connecting to Home Assistant..."]})})]})}im.createRoot(document.getElementById("root")).render(E.jsx(Ip.StrictMode,{children:E.jsx(qm,{})}));
