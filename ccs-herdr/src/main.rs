//! ccs-herdr: 把 ccs 的会话能力集成进 Herdr（Windows / Linux / macOS）。
//!
//! 纯 Rust 标准库实现，零第三方依赖，方便离线编译与跨平台分发。

mod agents;
mod ccs;
mod herdr;
mod json;
mod paths;
mod plugin;
mod tui;

use json::Json;
use std::collections::BTreeMap;
use std::path::Path;

const VERSION: &str = env!("CARGO_PKG_VERSION");

fn main() {
    let code = match run() {
        Ok(code) => code,
        Err(message) => {
            eprintln!("错误: {message}");
            1
        }
    };
    std::process::exit(code);
}

fn run() -> Result<i32, String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() {
        print_help();
        return Ok(0);
    }
    let rest = &args[1..];
    match args[0].as_str() {
        "list" => cmd_list(rest.contains(&"--json".to_string())),
        "open" => cmd_open(),
        "attach" => cmd_attach(rest),
        "restore" => cmd_restore(rest),
        "sync" => cmd_sync(),
        "bus-inbox" => cmd_bus_inbox(rest),
        "bus-send" => cmd_bus_send(rest),
        "install-plugin" => cmd_install_plugin(),
        "pane" => tui::run(),
        "doctor" => cmd_doctor(),
        "version" | "--version" | "-V" => {
            println!("ccs-herdr {VERSION}");
            Ok(0)
        }
        "help" | "--help" | "-h" => {
            print_help();
            Ok(0)
        }
        other => Err(format!("未知命令: {other}（用 help 查看用法）")),
    }
}

fn print_help() {
    println!("ccs-herdr {VERSION} - ccs x Herdr 集成（Windows/Linux/macOS）");
    println!();
    println!("用法:");
    println!("  ccs-herdr list [--json]              列出 ccs 会话");
    println!("  ccs-herdr open                        在 Herdr 新建 ccs 工作区并打开所有会话");
    println!("  ccs-herdr attach NAME [--pane ID]     把会话接入当前（或指定）Herdr 窗格");
    println!("  ccs-herdr restore [--open] [NAME...]  恢复 ccs 会话（可选同时打开窗格）");
    println!("  ccs-herdr sync                        把 session id 同步给 Herdr（原生恢复）");
    println!("  ccs-herdr bus-inbox [--as X] [--limit N]   查看 agent 消息");
    println!("  ccs-herdr bus-send --from X [--to Y|--group G] MSG  发送 agent 消息");
    println!("  ccs-herdr install-plugin              把 plugin/ 链接进 Herdr");
    println!("  ccs-herdr pane                        会话面板（数字键 attach）");
    println!("  ccs-herdr doctor                      诊断路径/依赖/守护进程");
    println!();
    println!("环境变量: CCS_HOME / CCS_BIN / HERDR_BIN_PATH / CCS_HERDR_HOME / CCS_HERDR_PLUGIN_DIR / HERDR_PANE_ID");
}

// ---------------------------------------------------------------- helpers
fn flag_value(args: &[String], name: &str) -> Option<String> {
    let mut i = 0;
    while i < args.len() {
        if args[i] == name && i + 1 < args.len() {
            return Some(args[i + 1].clone());
        }
        if let Some(value) = args[i].strip_prefix(&format!("{name}=")) {
            return Some(value.to_string());
        }
        i += 1;
    }
    None
}

fn jget<'a>(value: &'a Json, path: &[&str]) -> Option<&'a Json> {
    let mut current = value;
    for key in path {
        current = current.get(key)?;
    }
    Some(current)
}

fn jstr(value: &Json, path: &[&str]) -> Option<String> {
    jget(value, path)
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
}

fn load_map() -> BTreeMap<String, String> {
    let path = paths::map_file();
    let text = match std::fs::read_to_string(&path) {
        Ok(text) => text,
        Err(_) => return BTreeMap::new(),
    };
    let value = match json::parse(&text) {
        Ok(value) => value,
        Err(_) => return BTreeMap::new(),
    };
    let mut map = BTreeMap::new();
    if let Some(items) = value.as_obj() {
        for (key, val) in items {
            if let Some(s) = val.as_str() {
                map.insert(key.clone(), s.to_string());
            }
        }
    }
    map
}

fn save_map(map: &BTreeMap<String, String>) {
    let path = paths::map_file();
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let object = Json::Obj(
        map.iter()
            .map(|(k, v)| (k.clone(), Json::Str(v.clone())))
            .collect(),
    );
    let _ = std::fs::write(path, object.stringify());
}

fn fmt_age(seconds: f64) -> String {
    let sec = seconds.max(0.0) as u64;
    if sec < 60 {
        format!("{sec}s")
    } else if sec < 3600 {
        format!("{}m", sec / 60)
    } else if sec < 86400 {
        format!("{}h", sec / 3600)
    } else {
        format!("{}d", sec / 86400)
    }
}

fn running_sessions() -> Result<Vec<Json>, String> {
    Ok(ccs::sessions()?
        .into_iter()
        .filter(|s| s.get("status").and_then(|v| v.as_str()) == Some("running"))
        .collect())
}

// ---------------------------------------------------------------- commands
fn cmd_list(json_out: bool) -> Result<i32, String> {
    let sessions = ccs::sessions()?;
    let map = load_map();
    if json_out {
        println!("{}", Json::Arr(sessions).stringify());
        return Ok(0);
    }
    if sessions.is_empty() {
        println!("(没有 ccs 会话)");
        return Ok(0);
    }
    println!(
        "{:<16} {:<8} {:<10} {:<8} session id",
        "名字", "状态", "agent", "窗格"
    );
    for session in &sessions {
        let name = jstr(session, &["name"]).unwrap_or_else(|| "?".to_string());
        let status = jstr(session, &["status"]).unwrap_or_else(|| "?".to_string());
        let agent = jstr(session, &["agent"]).unwrap_or_else(|| "-".to_string());
        let sid = agents::session_id_of(session).unwrap_or_else(|| "-".to_string());
        let pane = map.get(&name).cloned().unwrap_or_else(|| "-".to_string());
        let age = session.get("age").and_then(|v| v.as_f64()).unwrap_or(0.0);
        println!(
            "{:<16} {:<8} {:<10} {:<8} {}  ({})",
            name,
            status,
            agent,
            pane,
            sid,
            fmt_age(age)
        );
    }
    Ok(0)
}

fn cmd_open() -> Result<i32, String> {
    let sessions = running_sessions()?;
    if sessions.is_empty() {
        println!("没有正在运行的 ccs 会话；先 ccs new NAME -- claude");
        return Ok(0);
    }
    let (code, value, stderr) = herdr::run_json(&[
        "workspace".to_string(),
        "create".to_string(),
        "--label".to_string(),
        "ccs".to_string(),
        "--no-focus".to_string(),
    ])?;
    if code != 0 {
        return Err(format!("创建 Herdr 工作区失败: {}", stderr.trim()));
    }
    let result = herdr::result_of(&value);
    let workspace = jstr(result, &["workspace", "workspace_id"])
        .ok_or_else(|| "Herdr 返回里没有 workspace id".to_string())?;
    let root_pane = jstr(result, &["root_pane", "pane_id"])
        .ok_or_else(|| "Herdr 返回里没有 pane id".to_string())?;

    let mut map = load_map();
    let mut opened: Vec<(String, String)> = Vec::new();
    let mut first = true;
    for session in &sessions {
        let name = match jstr(session, &["name"]) {
            Some(name) => name,
            None => continue,
        };
        let pane = if first {
            first = false;
            root_pane.clone()
        } else {
            let (code, value, stderr) = herdr::run_json(&[
                "tab".to_string(),
                "create".to_string(),
                "--workspace".to_string(),
                workspace.clone(),
                "--label".to_string(),
                name.clone(),
                "--no-focus".to_string(),
            ])?;
            if code != 0 {
                eprintln!("创建 tab 失败（{name}）: {}", stderr.trim());
                continue;
            }
            match jstr(herdr::result_of(&value), &["root_pane", "pane_id"]) {
                Some(pane) => pane,
                None => continue,
            }
        };
        let _ = herdr::run(&[
            "pane".to_string(),
            "rename".to_string(),
            pane.clone(),
            name.clone(),
        ]);
        let command = attach_command(&name);
        let (code, _, stderr) =
            herdr::run(&["pane".to_string(), "run".to_string(), pane.clone(), command])?;
        if code != 0 {
            eprintln!("窗格 {pane} 启动 ccs attach 失败: {}", stderr.trim());
        }
        map.insert(name.clone(), pane.clone());
        opened.push((name, pane));
    }
    save_map(&map);
    let _ = herdr::run(&[
        "workspace".to_string(),
        "focus".to_string(),
        workspace.clone(),
    ]);
    println!(
        "已在 Herdr 工作区 {workspace} 打开 {} 个会话窗格。",
        opened.len()
    );
    for (name, pane) in opened {
        println!("  {:<16} pane={}", name, pane);
    }
    Ok(0)
}

fn attach_command(name: &str) -> String {
    match ccs::ccs_bin() {
        Some(bin) => {
            let exe = bin.to_string_lossy().to_string();
            format!("\"{exe}\" attach \"{name}\"")
        }
        None => format!("ccs attach \"{name}\""),
    }
}

fn cmd_attach(args: &[String]) -> Result<i32, String> {
    let name = args
        .iter()
        .find(|arg| !arg.starts_with("--"))
        .cloned()
        .ok_or_else(|| "缺少会话名: ccs-herdr attach NAME".to_string())?;
    let pane = flag_value(args, "--pane")
        .or_else(|| std::env::var("HERDR_PANE_ID").ok())
        .filter(|p| !p.is_empty())
        .ok_or_else(|| {
            "不在 Herdr 窗格内（缺少 HERDR_PANE_ID）；可直接运行 ccs attach NAME".to_string()
        })?;
    let (code, _, stderr) = herdr::run(&[
        "pane".to_string(),
        "run".to_string(),
        pane.clone(),
        attach_command(&name),
    ])?;
    if code != 0 {
        return Err(format!("herdr pane run 失败: {}", stderr.trim()));
    }
    let mut map = load_map();
    map.insert(name.clone(), pane.clone());
    save_map(&map);
    println!("已在窗格 {pane} 中接入 {name}");
    Ok(0)
}

fn cmd_restore(args: &[String]) -> Result<i32, String> {
    let names: Vec<String> = args
        .iter()
        .filter(|arg| !arg.starts_with("--"))
        .cloned()
        .collect();
    let response = ccs::restore(&names)?;
    let started = response
        .get("started")
        .and_then(|v| v.as_arr())
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.as_str().map(|s| s.to_string()))
                .collect::<Vec<String>>()
        })
        .unwrap_or_default();
    let errors = response
        .get("errors")
        .and_then(|v| v.as_arr())
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.as_str().map(|s| s.to_string()))
                .collect::<Vec<String>>()
        })
        .unwrap_or_default();
    println!("已恢复 {} 个会话: {}", started.len(), started.join(", "));
    for error in &errors {
        println!("  失败: {error}");
    }
    if args.iter().any(|arg| arg == "--open") {
        return cmd_open();
    }
    Ok(0)
}

fn cmd_sync() -> Result<i32, String> {
    let map = load_map();
    let sessions = ccs::sessions()?;
    let mut done = 0;
    for (name, pane) in &map {
        let session = match sessions
            .iter()
            .find(|s| jstr(s, &["name"]).as_deref() == Some(name.as_str()))
        {
            Some(session) => session,
            None => continue,
        };
        let sid = match agents::session_id_of(session) {
            Some(sid) => sid,
            None => continue,
        };
        let agent = jstr(session, &["agent"]).unwrap_or_else(|| "generic".to_string());
        // Herdr TUI: herdr pane report-agent-session [OPTIONS] <PANE_ID> [-- RESUME_ARG...]
        let mut herdr_args = vec![
            "pane".to_string(),
            "report-agent-session".to_string(),
            "--source".to_string(),
            "ccs".to_string(),
            "--agent".to_string(),
            agent,
            "--agent-session-id".to_string(),
            sid,
            pane.clone(),
        ];
        if let Some(resume) = agents::resume_argv(session) {
            herdr_args.push("--".to_string());
            herdr_args.extend(resume);
        }
        let (code, _, stderr) = herdr::run(&herdr_args)?;
        if code == 0 {
            done += 1;
            println!("  {name} -> pane {pane} 已同步");
        } else {
            eprintln!("  同步 {name} 失败: {}", stderr.trim());
        }
    }
    println!("已向 Herdr 同步 {done} 个会话的 session id。");
    Ok(0)
}

fn pass_through(args: &[String]) -> Result<i32, String> {
    let bin = ccs::ccs_bin()
        .ok_or_else(|| "找不到 ccs 可执行文件（安装 ccs 或设置 CCS_BIN）".to_string())?;
    let status = std::process::Command::new(bin)
        .args(args)
        .status()
        .map_err(|e| format!("执行 ccs 失败: {e}"))?;
    Ok(status.code().unwrap_or(1))
}

fn cmd_bus_inbox(args: &[String]) -> Result<i32, String> {
    let mut ccs_args = vec!["bus".to_string(), "inbox".to_string()];
    if let Some(as_name) = flag_value(args, "--as") {
        ccs_args.push("--as".to_string());
        ccs_args.push(as_name);
    }
    if let Some(limit) = flag_value(args, "--limit") {
        ccs_args.push("--limit".to_string());
        ccs_args.push(limit);
    }
    pass_through(&ccs_args)
}

fn cmd_bus_send(args: &[String]) -> Result<i32, String> {
    let mut ccs_args = vec!["bus".to_string(), "send".to_string()];
    for flag in ["--from", "--to", "--group"] {
        if let Some(value) = flag_value(args, flag) {
            ccs_args.push(flag.to_string());
            ccs_args.push(value);
        }
    }
    let message = args
        .iter()
        .rev()
        .find(|arg| {
            !arg.starts_with("--") && flag_value(args, "--from").as_deref() != Some(arg.as_str())
        })
        .cloned()
        .ok_or_else(|| "缺少消息内容: ccs-herdr bus-send --from X --to Y MESSAGE".to_string())?;
    // 最后一个非 flag 参数作为消息（可能是多个词，按空格拼回）
    let start = args
        .iter()
        .position(|arg| arg == &message)
        .unwrap_or(args.len() - 1);
    let text = args[start..]
        .iter()
        .filter(|arg| !arg.starts_with("--"))
        .cloned()
        .collect::<Vec<String>>()
        .join(" ");
    ccs_args.push(text);
    pass_through(&ccs_args)
}

fn cmd_install_plugin() -> Result<i32, String> {
    match plugin::link() {
        Ok(message) => {
            println!("{message}");
            Ok(0)
        }
        Err(message) => Err(message),
    }
}

fn cmd_doctor() -> Result<i32, String> {
    println!("ccs-herdr {VERSION}");
    println!("平台        : {}", std::env::consts::OS);
    println!("数据目录    : {}", paths::data_dir().display());
    println!("映射文件    : {}", paths::map_file().display());
    println!("ccs 状态目录: {}", paths::ccs_home().display());
    println!("插件目录    : {}", plugin::plugin_dir().display());
    match ccs::ccs_bin() {
        Some(bin) => println!("ccs 可执行  : {}", bin.display()),
        None => println!("ccs 可执行  : 未找到（设置 CCS_BIN）"),
    }
    match herdr::herdr_bin() {
        Some(bin) => println!("herdr 可执行: {}", bin.display()),
        None => println!("herdr 可执行: 未找到（设置 HERDR_BIN_PATH 或安装 Herdr）"),
    }
    println!(
        "ccs 守护进程: {}",
        if ccs::ping() {
            format!("运行中 (port {:?})", ccs::daemon_port())
        } else {
            "未运行".to_string()
        }
    );
    if let Ok(plugin_dir) = std::fs::canonicalize(plugin::plugin_dir()) {
        println!("插件清单    : {}", plugin_dir.display());
    }
    let _ = Path::new(".");
    Ok(0)
}
