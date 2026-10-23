# R1 NLU 意图体系逆向全记录（分类 / 指令 / 调用链）

> 本文是对 `com.phicomm.speaker.device`（云知声 ANT 引擎 + 斐讯定制层，即 `fw/apk2/Unisound.apk`）
> 中 **NLU 分类体系、全部指令枚举、每个域的调用流程** 的源码级逆向记录，用于：
> 1) 自建 NLU 训练（域分类标签 = `service`，槽位 = `semantic.intent` 字段，动作 = `code` + `operations`）；
> 2) 自建服务按设备期待返回 JSON（协议格式见 [`nlu-protocol.md`](nlu-protocol.md)）。
> 所有行号/类名均来自反编译源，可直接检索验证。

## 0. 逆向来源（source of truth）

| 内容 | 来源 |
| --- | --- |
| 逆向对象 | `fw/apk2/Unisound.apk`（运行包名 `com.phicomm.speaker.device`，内置云知声 SDK） |
| Java 反编译 | jadx 1.5.0（`jadx/lib/jadx-1.5.0-all.jar`，WSL Java 17） → `D:\tmp\r1\out_uni_x\sources\` |
| smali 兜底 | apktool/baksmali → `D:\tmp\r1\uni_smali\` |
| 云端原始应答样本 | `r1tool asr -dump` 抓包：`D:\tmp\r1\audio\0001_*.bin`、`0020_resp.bin`（flat NLU 结构以此为准） |
| 离线命令词 | 设备内 `assets/nlu/unidrive_main_nlu_offline.conf`、`assets/commands/user_commands_config.xml` |

**关键源码文件 → 结论对照表**

| 结论 | 源文件（`out_uni_x/sources/` 下） |
| --- | --- |
| 唤醒/录音/上传参数 | `assets/config/config.mg`（`wakeup_benchmark=-9.1`、`wakeup_duration_for_continues=5000`、`oneshot_enable=false`） |
| flat NLU 验收门槛（`asr_recongize`+`retTag:"nlu"`）与 Mixture 组包 | `com/unisound/common/v.java` |
| NLU 分发、text 兜底（`net_nlu[0].text`）、-63551 | `com/unisound/vui/handler/filter/NLUDispatcher.java` |
| CHAT/SETTING_MP/ERROR_REPORT 的 `result_type=="full"` 过滤 | `com/unisound/vui/handler/filter/a.java` |
| service→类型解析（正则 `\W"service"\s*:\s*"([^",]+)"`） | `nluparser/a/e.java`（分类器）、`nluparser/c.java`、`nluparser/d.java`（service→TypeToken 映射） |
| 全部 handler 注册顺序 | `com/phicomm/speaker/device/ui/ExampleANTEngineInitializer.java:52-83` |
| 会话 handler 集体行为 | `com/unisound/vui/handler/session/**` |
| 斐讯定制层（灯光/音效/智能家居 IPC） | `com/phicomm/speaker/device/custom/**` |
| schema 枚举 (SName/SCode/Operator/Operands/Value) | `nluparser/scheme/*.java` |
| 音乐 Chúa状态上报 | `com/unisound/vui/handler/session/music/syncloud/MusicStateMgr.java` |

## 1. 全链路：唤醒 → ASR → NLU → 分发

```
libasrfix.so 本地唤醒（"小讯小讯"，阈值 config.mg → 打分 -9.1）
  → libaec.so 降噪 → ANTEngine 4 麦阵列
  → 开始 5 秒录音窗（固定窗口，非 VAD 截断）
  → 分块 POST http://asrv3.hivoice.cn/trafficRouter/cs   ← 一句 ≈17 个分块，Opus 16kHz 20ms/包
  → 最后一包 Content-Length:0 且带 TP/SP/CI/DT 头（或最后一个音频包响应提前挂结果）
  → 云端返回 flat NLU JSON（HTTP 头 CT:W510 / PN:ry / SID 回显）
```

 resultant flat JSON 进入设备后的流程：

```
① com.unisound.common.v.a(str, z, receiver) — 验收门槛：
     必须包含 "asr_recongize" 字样；且 retTag=="nlu" 或（无 retTag 且 !z 引擎态）；
     通过后剥离 retTag / asr_recongize / nluProcessTime，"\/" 反转义 → 存入 netNlu 列表
② 引擎收尾（final）：v 引擎回调（partial/full/change）构造 Mixture：
     {"net_asr":[{engine_mode:"net", result_type:"full|partial|change",
                  last_result:bool, recognition_result:…, session_id:…}],
      "net_nlu":[<清洗后的 flat NLU>, ...]}
③ NLUDispatcher.onASRResultNet → MixtureProcessor.from(mixture)：
     nluparser/a/e.java 用正则 \W"service"\s*:\s*"([^",]+)" 取 service →
     c.java/d.java Map 里查 Gson TypeToken；查不到 → 默认 Mixture<NullIntent,NullResult>
④ NLUDispatcher.b(mixture)：nluList 为空直接丢
⑤ a(ctx, str, mixture)：
     - filter.a（filter/a.java）：service ∈ {SETTING_MP, CHAT, ERROR_REPORT} 且
       net_asr[0].result_type != "full" → 丢弃（部分识别结果不触发闲聊）
     - str2 = net_nlu[0].text 作兜底播报文本（NLUDispatcher.java:278 附近）
     - b(ctx,nlu) 预处理：text 为空 → 统一 -63551 错误 NLU（ERROR_REPORT 域）
⑥ fireASREvent(1102) → cancelEngine() → fireUserEventTriggered(nlu) → ANTEngine pipeline 逐 handler 传递
```

**pipeline 注册顺序**（`ExampleANTEngineInitializer.onEngineInitDone`，NLU 在 pipeline 里从前到后）：

| # | Handler | 角色 |
| --- | --- | --- |
| 1 | `NLUDispatcher(MixtureProcessor)` | 分发/过滤/兜底 |
| 2 | `PhicommDataStatisticHandler` | 埋点（含 MixtureProcessor 便于旁路解析） |
| 3 | `PhicommReminderHandler` | 提醒域 |
| 4 | `PhicommAlarmHandler` | 闹钟域 |
| 5 | `DefaultMemoRingingHandler`（RingingEventProcessor） | 提醒/闹钟响铃执行 |
| 6 | `PhicommInterceptHandler(PhicommLightListener)` | 拦截 NLU 里灯光指令 → 呼吸灯驱动 |
| 7 | `DefaultLightsHandler` | 灯光域 |
| 8 | `PhicommTTSHandler` | TTS 播报出口 |
| 9 | `SimpleSessionManager` | 会话管理（interrupt 判定/会话优先级闸门） |
| 10 | `DeviceCenterHandler.associateEngine(...)` | 设备中心/MQTT 栈（绑定、子设备） |
| 11 | `PhicommWakeupWordChangedHandler` | 唤醒词更变后续 |
| 12 | `PhicommBindStatusHandler` | APP 绑定状态 |
| 13 | `DefaultANTLaunchHandler` | ANT 应用启动 |
| 14 | `DefaultWeatherHandler` | 天气域 |
| 15 | `DefaultStockHandler` | 股票域 |
| 16 | `PhicommExternalMusicHandler(PhicommExternalPlayer)` | 音乐域（外置像素仓逻辑，先收） |
| 17 | `PhicommMusicHandler(PhicommPlayer)` | 音乐域（主链路，CommonPlayer ServiceConnection） |
| 18 | `PhicommMusicScheduleHandler` | 音乐电台 schedule |
| 19 | `DefaultNoteHandler` | 备忘录/便签 |
| 20 | `DefaultSettingHandler(PhicommSettingHandler)` | 设置家族（本机+智能家居） |
| 21 | `DefaultChatHandler` | 闲聊（在设置后才收，只有闲聊能被"打断"判定进入） |
| 22 | `DefaultGuideHandler` | 唤醒/引导 |
| 23 | `DefaultIlleageChatHandler` | 违规问答 |
| 24 | `DefaultSmartHomeHandler` | 智能家居兜底 |
| 25 | `DefaultUnSupportHandler` | 不支持域兜底话术 |
| 26 | `PhicommInitializeHandler` / `PhicommStatusHandler` | 初始化/状态广播 |

> 注意：SDK 里还有 `DefaultSceneModeHandler`、`DefaultStockHandler` 等未在 Example 初始化里注册的
> handler；固件实际生效的是上表 26 个。域判断时以 pipeline 里谁先 `accept` 为准。

## 2. 分类体系（训练标签即 `service` 字符串）

`nluparser/scheme/SName.java` 73 个 service（节选常用的，全部可用于域分类）：

```
cn.yunzhisheng.call | callmonitor | contact | sms   打电话/通话/联系人/短信
cn.yunzhisheng.chat / chat.chat_with_tag / chat.chitchat / chat_translation
cn.yunzhisheng.music / audio / fm / novel / blog / news / broadcast / cookbook /
    edible_drug / website / websearch / local_addr / localsearch / map / movie /
    video / weather (weather_result) / stock / calendar / calculator / hotel /
    flight / traffic.congest / traffic_subsidiary / traffic.poi
cn.yunzhisheng.setting / setting.common / setting.mp / setting.air / setting.ac /
    setting.tv / setting.fan / setting.bathheater / setting.light /
    setting.curttain(注意拼写) / setting.window_curtain / setting.voicebox
cn.yunzhisheng.device_center / device_report / device_bind / monitor_list / hotel_service
cn.yunzhisheng.global.cmd / scenemode / appmgr / ota / wakeupword / health.info /
    ant_launch / error / note / reminder / alarm / announcer / connect
cn.yunzhisheng.scenemode (场景模式) | cn.yunzhisheng.microblog (微博)
service_navigation (旧字段)
```

**service → Gson 类型映射**（MixtureProcessor 内 `nluparser/c.java`；全文 Gson 解析）：

| service 族 | intent/result 类型 |
| --- | --- |
| music | Mixture<MusicIntent, MusicResult> |
| audio | Mixture<AudioIntent, AudioResult> |
| setting / setting.common / setting.mp / setting.air | Mixture<SettingExtIntent, NullResult> |
| alarm | Mixture<AlarmIntent, NullResult> |
| reminder | Mixture<ReminderIntent, NullResult> |
| weather | Mixture<NullIntent, WeatherResult> |
| stock / news / broadcast / video | Mixture<NullIntent, StockResult / NewsResult / BroadcastResult / Result> |
| translation | Mixture<TranslateIntent, TranslateResult> |
| scenemode | Mixture<SceneModeIntent, NullResult> |
| global.cmd | Mixture<GlobalCmdIntent, NullResult> |
| 其它 / 无 service | Mixture<NullIntent, NullResult>（只走 general.text 播报路径） |

> **设计含义**（对训练最重要）：**域分类的 ground truth = `service`；动作分类 = `code`；
> 槽位抽取 = `semantic.intent` 里该域的 Intent 字段**。第 4/5 节给出完整枚举与 schema。

## 3. 每个 code 的调用流程（全量 code 与触发链）

`nluparser/scheme/SCode.java` 66 个 code，按域分组：

### 3.1 设置家族（本机动作，链路最深）

**入口统一**: `DefaultSettingHandler.eventReceived` → `getSettingIntent(nlu)`：

1. `nlu.getSemantic().getIntent()` 强转 `SettingExtIntent`（**每个 setting 域的 operations 必须非空**，否则空对象二次强转 `SettingIntent` 崩）。
2. 按 service 分支 type：

| service | type | 行为 |
| --- | --- | --- |
| cn.yunzhisheng.setting | 0 | 本机定制 + 智能家居转发 |
| cn.yunzhisheng.setting.common | 1 | 音量/静音/唤醒词等"本地属性" |
| cn.yunzhisheng.global.cmd | 2 | 全局取消（intent.confirm==ACT_CANCEL → 中断一切） |
| cn.yunzhisheng.health.info | 3 | 直接 `PhicommSettingHandler.sendPhicommSmartHomeCommand`（IPC） |
| cn.yunzhisheng.setting.air | 4 | 同上（空调操作原生走 IPC） |

3. type 0/1 内部按 `operations[0].operands` 分派（`Operator`/`Operands` 见第 5 节）。

**本机专属 operands → 调用链**（`com/phicomm/speaker/device/custom/setting/PhicommSettingHandler.java`）：

| operands | PhicommSettingHandler | 调用链 |
| --- | --- | --- |
| `AmbientLight` | `ACT_PHICOMM_OPEN/CLOSE_AMBIENTLIGHT` | handleOrder → `openAmbientLight()`：写系统 LED 节点（`/sys/class/leds/...`，PhicommLightListener 同源），失败/成功各播一句 |
| `SoundEffect` | `ACT_PHICOMM_OPEN/CLOSE_SOUNDEFFECT` | handleOrder → `openSoundEffect()`：设置重低音开关（一次只能一个 sound mode） |
| `OBJ_BLUETOOTH` | `ACT_PHICOMM_OPEN/CLOSE_BLUETOOTH` | 切换蓝牙模式（切 BT-in 扬声器模式），播报进度 |
| `OBJ_SLEEP_MODE` | `ACT_PHICOMM_OPEN_SLEEP_MODE` | 睡眠模式（灯环熄灭 + 双击休眠策略） |
| 本机仅面板（OpenWrt） | `ATTR_*` 参数调节 | 参数写入 UserPerference，成功播报 + `onSetting**Done` 回调 |

**Deleting/智能家居转发 operands**（`isPhicommSmartHome(nlu,true)` 白名单，任何其一命中→转 IPC）：

```
operands 或 value 命中:
  OBJ_LIGHT (灯光→非本机 LED，指智能家居灯) / OBJ_AC / OBJ_FAN / OBJ_CURTAIN /
  OBJ_HUMIDIFIER / OBJ_DEHUMIDIFIER / OBJ_WATER_DISPENSER / OBJ_WATER_HEATER /
  OBJ_FRIDGE / OBJ_KITCHEN_VENTILAT / OBJ_OUTLET / OBJ_ROUTER /
  ATTR_HOME_AIRQUALITY / OBJ_AIR_CLEANER / ATTR_WIND_SPEED /
  ATTR_MODE ∈ {MODE_GUEST, MODE_LEAVE_HOME, MODE_GO_HOME, MODE_MORNING,
               MODE_SLEEP, MODE_DINING, MODE_MOVIE}
```

```
→ code = SETTING_IOT（或命中的 setting 普通指令）
→ PhicommSettingHandler.sendPhicommSmartHomeCommand(nlu):
     mMsgCenter.sendMessage(0x800000 /*8388608*/, JsonTool.toJson(NLU))
     注册接收器 id 0x1000000 /*16777216*/
     → IPC 进伴侣 App 的 EchoService / 直连 PhicommIotClient
     ← PhicommIotResponse.getText() 回填播报
     超时 → 本地"智能家居响应超时"兜底
     （device center 会另外把该 NLU 存到 FullLog 用于离线补发 — DeviceCenterHandler 侧）
```

**音量链路**（type 1, `ATTR_VOLUME`）：

```
ACT_INCREASE/DECREASE → 播报已经按步进更新；ACT_MAX/MIN → 上下限分支
ACT_SET → intent.datatype == "int"|"percent" + value(1..100)
          → 非法 → 修正为默认 60 播"已经设置音量为 X"
百分为空时也走 int 分支 → 注意 ACT_SET 必须给 value
```

**唤醒词链路**（type 1 也可以走 `ATTR_WAKEUP_WORD` / `ATTR_NAME`）：

```
ACT_SET + value（2~3 个汉字正则校验，其它字符 → 播"唤醒词不合法"）
→ 写 UserPerference + 通知本地 libasrfix 重新加载
→ 成功 onWakeupEventSetWakeupwordDone；失败回调 3107（"设置失败"）
→ PhicommWakeupWordChangedHandler 广播更新 UI/App
```

**APP 升级/备份/一键反馈/在线状态**（type 0, `handleOrder(str)` 直答 + stopTTS/stopASR 后发 msgcenter 消息 16384/…/5/6/7 → `PhicommOTAService`/BackupService 处理）。

### 3.2 多媒体家族

**播歌**（`PhicommExternalMusicHandler`(先收) / `PhicommMusicHandler`(主链路)）：

```
code ∈ {SEARCH_SONG, SEARCH_SONGLIST, SEARCH_ALBUM, SEARCH_ARTIST,
        SEARCH_BILLBOARD, SEARCH_CATEGORY, SEARCH_RANDOM, SEARCH_TAG,
        SEARCH_FM_SONG, SEARCH_TRAIL_PLAY}
→ MusicIntent{album, artist, artistType, billboard, episode, genre, keyword,
              language, lyrics, mood, musicTag, scene, song, songlist}
→ data.result.count / data.result.musicinfo[{id, errorCode, duration(ms),
              lyric, album, artist, hdImgUrl, isCollected, title, url}]
    url 无效 / 列表为空 → 播"没有找到这首歌"之类
    有效 → taskHandler.sendMessage: 进入 CommonPlayer(pos 进度) →
            PhicommPlayer(ServiceConnection) → msgcenter → echoplayer 进程播放
→ 播放中每 30s: MusicStateMgr.onReportMusicStatus(MusicData) 上报 (msgcenter→MQTT)
→ 音乐 url 必须能被 R1 MediaPlayer 要求: 直链 200/206、Content-Type audio/*;
   对象存储杂头会卡 PREPARING（见 nlu-protocol.md §3.3 实测坑）
```

**播放控制**（`cn.yunzhisheng.setting.mp`，SETTING_EXEC_MP code）：

```
operations[0] { ACT_PLAY | ACT_PAUSE | ACT_STOP | ACT_PREV | ACT_NEXT |
                ACT_FASTB | ACT_FASTF | ACT_GEAR_GOTO | ACT_NUM_GOTO |
                ACT_PLAY_AUDIO_LIST | ACT_COLLECT | ACT_CANCEL_COLLECT .. }
operands ∈ {ATTR_FASTB_TIME, ATTR_FASTF_TIME, ATTR_PLAY_MODE, ATTR_SOURCE,
             OBJ_MEDIA_PLAYER, OBJ_MUSIC, OBJ_ALBUM, OBJ_BILLBOARD, OBJ_FM, ...}
value 可选 (e.g. ACT_GEAR_GOTO → ACT_GEAR_GOTO_LOW/MIDDLE/HIGH 注意是 value)
ACT_SWITCH_PLAY_MODE (value="switchPlayMode") → 循环模式切换
→ PhicommExternalMusicHandler priority 定制 + PhicommMusicScheduleHandler 分流游戏电台
```

### 3.3 闹钟 / 提醒（本地完全闭环，云只回 intent）

**闹钟**（`PhicommAlarmHandler` + );`AbstractMemoHandler` 校验 → `MemoUtils.generateAlarmMemo`:

```
code = ALARM_SET     type=0: date "yyyy-MM-dd" + time "HH:mm[:ss]" 必填
                     repeatDate ∈ {OFF, DAY, WORKDAY, WEEKEND, MON..SUNDAY}
                       （MONTH/YEAR 无效 → 播"暂时不支持按月/年重复"）
                     label 可空
code = ALARM_SET_TIMING  type=1: countDownTime ms ≥ 10000 (10s)
                     直接 generateCountdownMemo
非法 → 返回 alarm 校验 tts alarm_set_intent_error 各分支
合法 → AbstractMemoHandler 正常流程 → evenTe 写入 litepal(支持多闹钟) →
       AlarmReceiver ACTION cn.yunzhisheng.action.ring 到点响(自副警铃)
       MEMO_RINGING_VALID_TIME_OFFSET=3000ms 有效性窗口
       → DefaultMemoRingingHandler(RingingEventProcessor) 响铃 → 等待用户响应
```

**提醒**（`PhicommReminderHandler`，`AbstractMemoHandler` 同源）：

```
code = REMINDER_SET
  intent.dateTime "yyyy-MM-dd HH:mm" 必填；content 必填（"要不要提醒"内容非空）
  repeatType ∈ {OFF, DAY, WORKDAY, WEEKEND, MON..SUNDAY}
  checkMemoCount("reminder") 超上限 → 播"提醒数量已达上限"
合法 → getMemoContent 入库 → tts_reminder_set_result_ok(time, content)
REMINDER_CANCEL/REMOVE/REMOVE_ALL → 本地不支持，直接播回复（"did it locally"？实测为不支持台词）
```

**便签/笔记备忘**（`DefaultNoteHandler`）：

```
code = ANSWER → 进入补充录音模式（该 Code 只有在 memo/note 会话中被消费）
code = NOTE_DELETE / NOTE_QUERY(纯本地库 litepal 查询) / NOTE_RESET_QUERY
```

### 3.4 天气 / 股票 / 新闻 等查询域

```
DefaultWeatherHandler: 无 code 判断！只看 data.result 有无
  data.result != null → 播 data.header（云端生成播报词 header/headerTts）
  data.result == null → 播"抱歉，没有查到该地区天气"
  → stopWakeup/stopASR/playTTS
DefaultStockHandler: 同类，StockResult{marketData, dayStockData, codeName, price, ...}
Broadcast/News: NewsResult{list[{title, content, source, time}]}, 电台类列表
```

### 3.5 闲聊 / 引导 / 不支持 / MQTT 设备中心

```
DefaultChatHandler (service=cn.yunzhisheng.chat):
  style empty + url empty → 播 general.text
  style ∈ {joke, poem, translation} 且 url/audio → 播链接音频
  style = unknown / maybe_noise → 随机兜底句
  （注：filter.a 要求 CHAT 结果 result_type=="full" 才不允许被 channel 丢弃）
DefaultGuideHandler / DefaultIlleageChatHandler / DefaultUnSupportHandler:
  bluetooth_error code → 直接 TTS nlu.text（蓝牙连接失败播报）
  其它 sv/c → 统一"暂时不明白"兜底句
DefaultSmartHomeHandler: 上面 setting 没接住的 Roam 类兜底
DeviceCenterHandler: 所有 NLU 同步进 FullLog 带上 device center 消息队列
  （绑定/子设备/音乐收藏入 app），MQTT 推送侧见 voice-assistant.md 组件表
```

## 4. 指令枚举总表（训练"动作"分类）

### 4.1 `Operator.java`（operations[].operator 全集）

```
基本态: ACT_OPEN ACT_CLOSE ACT_SET ACT_UNSET ACT_QUERY ACT_CANCEL("CANCEL")
        ACT_CHANGE ACT_RESTART ACT_RESUME ACT_PAUSE ACT_STOP
播放态: ACT_PLAY ACT_PREV ACT_NEXT ACT_BOOKMARK ACT_GEAR_GOTO ACT_NUM_GOTO
        ACT_FASTB ACT_FASTF ACT_STOP_FASTB ACT_STOP_FASTF ACT_SWITCH
        ACT_PLAY_LIST ACT_PLAY_AUDIO_LIST ACT_COLLECT ACT_CANCEL_COLLECT
        ACT_DOWNLOAD ACT_INSTALL ACT_FEEDBACK ACT_REPLAY ACT_LAST
        ACT_QUESTION_VERSION ACT_LATEST_TASK
增量态: ACT_INCREASE ACT_DECREASE ACT_MAX ACT_MIN
斐讯定必: ACT_PHICOMM_OPEN/CLOSE_AMBIENTLIGHT  ACT_PHICOMM_OPEN/CLOSE_SOUNDEFFECT
        ACT_PHICOMM_OPEN/CLOSE_BLUETOOTH  ACT_PHICOMM_OPEN_SLEEP_MODE
        ACT_PHICOMM_SMART_HOME  ACT_PHICOMM_BACKUP  ACT_PHICOMM_OTA
        ACT_PHICOMM_VERSION  ACT_PHICOMM_CHECK_ONLINE_STATE
```

### 4.2 `Operands.java`（operations[].operands 全集 62 项）

```
本机属性: ATTR_VOLUME  ATTR_BRIGHTNESS  ATTR_COLOR  ATTR_WAKEUP_WORD
          ATTR_NAME  ATTR_SPEED  ATTR_WIND..  ATTR_TEMPERATURE  ATTR_HUMIDITY
          ATTR_AIR_QUALITY  ATTR_HOME_AIRQUALITY  ATTR_POWER  ATTR_STATUS
          ATTR_SCENE  ATTR_TIMER  ATTR_VERSION  ATTR_DEVICE_NAME
          ATTR_MAC / ATTR_IP / ATTR_UUID  ATTR_MODE
智能家居对箱(valid → 转 IPC): OBJ_LIGHT  OBJ_AC  OBJ_FAN  OBJ_CURTAIN
          OBJ_HUMIDIFIER  OBJ_DEHUMIDIFIER  OBJ_WATER_DISPENSER
          OBJ_WATER_HEATER  OBJ_FRIDGE  OBJ_KITCHEN_VENTILAT  OBJ_OUTLET
          OBJ_ROUTER  OBJ_POWER_STRIP  OBJ_AIR_CLEANER  ATTR_WIND_SPEED
本机设备管理: OBJ_BLUETOOTH  OBJ_WIFI  OBJ_SLEEP_MODE  OBJ_TTS_MODLE
          OBJ_DIALOG  OBJ_MEDIA_PLAYER  OBJ_RINGTONE  OBJ_AUTOLIGHT
          OBJ_AUTO_CLEAN ...
MP 加减控制: OBJ_ALBUM/OBJ_BILLBOARD/OBJ_FM/OBJ_MUSIC/OBJ_CHANNEL_CATEGROY ...
```

### 4.3 `Value.java`（value/枚举子值）

```
模式: MODE_GUEST MODE_LEAVE_HOME MODE_GO_HOME MODE_MORNING MODE_SLEEP MODE_DINING
      MODE_MOVIE MODE_MUTE MODE_ALARM MODE_ALL_OFF MODE_ALL_ON MODE_AUTO
      MODE_COOL MODE_WARM MODE_ECO MODE_PURIFICATION MODE_VENTILATION MODE_HUMIDIFICATION ...
颜色: COLOR_RED COLOR_BLUE COLOR_GREEN COLOR_YELLOW COLOR_WHITE COLOR_PURPLE
      COLOR_PINK COLOR_ORANGE COLOR_CYAN COLOR_BREATH COLOR_CHANGE COLOR_AUTO
亮度: BRIGHT_AUTO BRIGHT_HIGH BRIGHT_LOW BRIGHT_MEDIUM BRIGHT_SHINING BRIGHT_SOFT
风速: WIND_SPEED_LOW WIND_SPEED_MEDIUM WIND_SPEED_HIGH
状态: STATUS_OPEN STATUS_CLOSED STATUS_HALF_OPEN STATUS_ALL_OPEN
房间: ROOM_BED_ROOM ROOM_LIVING_ROOM ...（智能家居路径）
```

### 4.4 `SCode.java` 全量速查（按域）

| code | 域 / 触发链小结 |
| --- | --- |
| `ALARM_SET` / `ALARM_SET_TIMING` / `ALARM_CANCEL` / `ALARM_REMOVE` / `ALARM_REMOVE_ALL` / `ALARM_STOP` | 闹钟（§3.3）；CANCEL/REMOVE 只本地播回复不支持 |
| `REMINDER_SET` / `REMINDER_CANCEL` / `REMINDER_REMOVE` / `REMINDER_REMOVE_ALL` | 提醒（§3.3） |
| `ANSWER` | memo/note 会话内补充问（其余域不被消费） |
| `NOTE_DELETE` / `NOTE_QUERY` / `NOTE_RESET_QUERY` | 便签（§3.3） |
| `SEARCH_SONG/SONGLIST/ALBUM/ARTIST/BILLBOARD/CATEGORY/RANDOM/TAG/FM_SONG/TRAIL_PLAY` | 音乐搜索（§3.2） |
| `ACT_SWITCH_PLAY_MODE`（value="switchPlayMode"） | 循环模式 |
| `SETTING_EXEC` / `SETTING_IOT` / `SETTING_EXEC_MP` / `SETTING_EXEC_AC` / `SETTING_EXEC_TV` / `USER_COMMAND` | 设置家族（§3.1） |
| `CONNECT_WIFI` | 配网入口 |
| `WAKEUP_WORD` | 唤醒词入口（引导域） |
| 音乐: `foreground` | PhicommMusicScheduleHandler 特殊细分 |
| APP/OTA: `APP_LAUNCH / APP_EXIT / APP_UNINSTALL` | appmgr |

### 4.5 各域 Intent 字段 schema（训练"槽位抽取"）

| intent | 字段（逗号分隔） |
| --- | --- |
| MusicIntent | album, artist, artistType, billboard, episode, genre, keyword, language, lyrics, mood, musicTag, scene, song, songlist |
| SettingIntent (operations 单元) | operator, operands, confirm, datatype, value, valueDelta, valueDeltaExpr, percentValue, percentValueDelta, percentValueDeltaExpr, device, deviceType, deviceExpr, home, homeExpr, room, roomExpr, roomType, zone, time, timeDelta, timeExpr, timeDeltaExpr, offsetTime, anchorTime, endTime, duration, repeat |
| AlarmIntent | date, time, repeatDate, label, countDownTime, (type int: 0/1) |
| ReminderIntent | content, dateTime, event, eventTime, isSubscribe, repeatType, topic, triggerType |
| WeatherResult | errorCode, focusDateIndex, updateTime, cityName, cityCode, weatherDays[{dayOfWeek, weather, wind, quality, pm2_5, currentTemperature, highestTemperature, lowestTemperature, suggest, *Index(运动/穿衣等), *Desc}] |
| SceneModeIntent | modeState, isOpen, sceneName, startTime, stopTime, lightParam{brightness, lightColor, lightEffectType}, speakerParam, smartAppliancesParam |
| TranslateIntent/Result | source/langu...(源语/目标语/原文/译文) |

## 5. 自建服务返回 JSON 样例（可直接进入训练/联调）

> 每条都必须有 `asr_recongize` + `retTag:"nlu"`（v.java 门槛），text 非空（NLUDispatcher 空文本 → -63551）。
> 聊天/闲聊/SETTING_MP 三域额外要求 result_type=="full"（filter.a）——由引擎自动满足最终包。

```json
// ① 闲聊/LLM 回答（默认域，不要用 ANSWER！ANSWER 只被 memo/note 消费）
{"service":"cn.yunzhisheng.chat","code":"cn.yunzhisheng.chat","rc":0,"retTag":"nlu",
 "asr_recongize":"你好","text":"你好呀，我是你的音箱",
 "general":{"type":"T","text":"你好呀，我是你的音箱"}}

// ② 查天气（DefaultWeatherHandler 直接播 data.header）
{"service":"cn.yunzhisheng.weather","code":"FORECAST","rc":0,"retTag":"nlu",
 "asr_recongize":"今天北京天气","text":"今天北京晴，2 到 12 度",
 "data":{"header":"今天北京晴，2 到 12 度",
         "result":{"errorCode":0,"cityName":"北京","focusDateIndex":0,"weatherDays":[...]}}}

// ③ 氛围灯开（AmbientLight → PhicommSettingHandler 本机 LED）
{"service":"cn.yunzhisheng.setting","code":"SETTING_EXEC","rc":0,"retTag":"nlu",
 "asr_recongize":"打开氛围灯","text":"好的，已打开氛围灯",
 "semantic":{"intent":{"operations":[
     {"operator":"ACT_OPEN","confirm":"ACT_OPEN","operands":"AmbientLight"}],
     "voiceTip":"","musicInfo":[]}}}

// ④ 重低音开（SoundEffect）
{"...同 ③ 骨架",
 "semantic":{"intent":{"operations":[{"operator":"ACT_OPEN","operands":"SoundEffect"}]}}}

// ⑤ 空气净化器（SETTING_IOT → IPC 智能家居 → 伴侣 App）
{"service":"cn.yunzhisheng.setting","code":"SETTING_IOT","rc":0,"retTag":"nlu",
 "asr_recongize":"打开空气净化器","text":"好的",
 "semantic":{"intent":{"operations":[
     {"operator":"ACT_OPEN","operands":"OBJ_AIR_CLEANER","deviceType":"AirCleaner"}]}}}

// ⑥ 音量调大 / 音量设为 50 / 静音
{"...骨架同 ③","service":"cn.yunzhisheng.setting.common",
 "semantic":{"intent":{"operations":[{"operator":"ACT_INCREASE","operands":"ATTR_VOLUME"}]}}}
{"...","semantic":{"intent":{"operations":[{"operator":"ACT_SET","operands":"ATTR_VOLUME","value":"50","datatype":"int"}]}}}
{"...","semantic":{"intent":{"operations":[{"operator":"ACT_SET","operands":"ATTR_MODE","value":"MODE_MUTE"}]}}}

// ⑦ 闹钟（明早七点半叫我 → 设备本地建闹钟+响铃）
{"service":"cn.yunzhisheng.alarm","code":"ALARM_SET","rc":0,"retTag":"nlu",
 "asr_recongize":"明早七点半叫我","text":"好的",
 "semantic":{"intent":{"date":"2026-10-24","time":"07:30:00","repeatDate":"OFF","label":""}}}
// 倒计时 5 分钟
{"service":"cn.yunzhisheng.alarm","code":"ALARM_SET_TIMING",...,
 "semantic":{"intent":{"countDownTime":300000,"label":"","repeatDate":"OFF"}}}

// ⑧ 提醒
{"service":"cn.yunzhisheng.reminder","code":"REMINDER_SET","rc":0,"retTag":"nlu",
 "asr_recongize":"六点提醒我喝水","text":"好的",
 "semantic":{"intent":{"content":"喝水","dateTime":"2026-10-24 18:00","repeatType":"OFF"}}}

// ⑨ 暂停播放（setting.mp 家族）
{"service":"cn.yunzhisheng.setting.mp","code":"SETTING_EXEC_MP","rc":0,"retTag":"nlu",
 "asr_recongize":"暂停","text":"好的",
 "semantic":{"intent":{"operations":[{"operator":"ACT_PAUSE"}],"voiceTip":"","musicInfo":[]}}}

// ⑩ 点歌（url 必须是 R1 可播的直链，建议经 /media 代理改写，见 voice-assistant.md §9）
{"service":"cn.yunzhisheng.music","code":"SEARCH_SONG","rc":0,"retTag":"nlu",
 "asr_recongize":"来一首旅行的意义","text":"为您播放陈绮贞的旅行的意义",
 "semantic":{"intent":{"artist":"陈绮贞","song":"旅行的意义"}},
 "data":{"result":{"count":1,"musicinfo":[
   {"id":1,"errorCode":0,"duration":326414,"lyric":"","album":"华丽的冒险",
    "artist":"陈绮贞","title":"旅行的意义","isCollected":false,
    "hdImgUrl":"...","url":"http://.../xxx.mp3"}]}}}
```

## 6. 对旧文档的更正（以本文为准）

1. `nlu-protocol.md` §3.1 的 `code:"ANSWER"` "万能闲聊"——**不对**：`ANSWER` 只被
   `AbstractMemoHandler`/`DefaultNoteHandler` 消费；闲聊必须 `service:"cn.yunzhisheng.chat"` + `general.text`。
2. `nlu-protocol.md` §3.2/§4 的样例没有 `asr_recongize` + `retTag:"nlu"`：实测必须带，否则 `v.a()` 整条丢弃。
3. setting 家族不是"operations 随意"：必须是 `SettingExtIntent` 结构，`operations` 非空数组，否则 ClassCastException。
4. "本地有的是规则判断"实际是：本地只有**离线命令词**（`USER_COMMAND` 的 fixed 列表）；域分类/槽位全在云端返回的 NLU 结构里。

## 7. 训练数据建议

- **域分类**：以 `service` 全集（§2）为标签空间；实际高频只需覆盖 §5 的 10 类 + weather/music/chat。
- **动作分类**：每个域一个 code 集合（§4.4）；setting 家族再细分 operator。
- **槽位抽取**：每个 intent schema（§4.5）的实体字段；`repeatDate` 小枚举可做 closed-set 分类。
- **回复词**：alarm/reminder/alarm 定时/音量调节/唤醒词设置是设备本地播报（云不需要生成文案），
  只有 chat（general.text）、weather（data.header）、bluetooth_error 需要云侧生成 TTS 文本。
- 可把第 5 节样例直接转成训练目标 JSON（utterance → JSON）做生成式 NLU 评测。
