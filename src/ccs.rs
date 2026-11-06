//! 与 ccs 守护进程通信（TCP + 单行 JSON，与 ccs 的 Python 实现协议一致）。

use crate::json::{self, Json};
use crate::paths;
use std::io::{BufRead, BufReader, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::Command;
use std::time::{Duration, Instant};

pub fn daemon_port() -> Option<u16> {
    let file = paths::ccs_home().join("daemon.json");
    let text = std::fs::read_to_string(file).ok()?;
    let value = json::parse(&text).ok()?;
    value.get("port")?.as_i64().map(|n| n as u16)
}

pub fn rpc(request: &Json) -> Result<Json, String> {
    let port = daemon_port().ok_or_else(|| {
        "ccs 守护进程未运行（找不到 daemon.json）。先执行 ccs daemon start".to_string()
    })?;
    let mut stream = TcpStream::connect(("127.0.0.1", port))
        .map_err(|e| format!("连接 ccs 守护进程失败: {e}"))?;
    stream
        .set_read_timeout(Some(Duration::from_secs(30)))
        .map_err(|e| format!("设置超时失败: {e}"))?;
    let line = request.stringify() + "\n";
    stream
        .write_all(line.as_bytes())
        .map_err(|e| format!("发送请求失败: {e}"))?;
    let mut reader = BufReader::new(stream);
    let mut response = String::new();
    reader
        .read_line(&mut response)
        .map_err(|e| format!("读取响应失败: {e}"))?;
    if response.trim().is_empty() {
        return Err("ccs 守护进程关闭了连接".to_string());
    }
    json::parse(&response).map_err(|e| format!("守护进程响应不是 JSON: {e}"))
}

pub fn ping() -> bool {
    let request = Json::Obj(vec![("k".to_string(), Json::Str("ping".to_string()))]);
    match rpc(&request) {
        Ok(value) => value.get("k").and_then(|v| v.as_str()) == Some("pong"),
        Err(_) => false,
    }
}

pub fn ccs_bin() -> Option<PathBuf> {
    if let Some(v) = std::env::var_os("CCS_BIN") {
        if !v.is_empty() {
            let path = PathBuf::from(v);
            if path.is_file() {
                return Some(path);
            }
        }
    }
    // 安装包内置的 ccs 引擎：<ccs-herdr.exe 目录>/engine/ccs.exe
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            for rel in ["engine/ccs.exe", "engine/ccs", "ccs.exe"] {
                let candidate = dir.join(rel);
                if candidate.is_file() {
                    return Some(candidate);
                }
            }
        }
    }
    paths::which("ccs")
}

pub fn ensure_daemon() -> Result<(), String> {
    if ping() {
        return Ok(());
    }
    let bin = ccs_bin().ok_or_else(|| {
        "找不到 ccs 可执行文件。请先安装 ccs，或设置 CCS_BIN 指向 ccs 可执行文件".to_string()
    })?;
    let status = Command::new(&bin)
        .arg("daemon")
        .arg("start")
        .output()
        .map_err(|e| format!("启动 ccs 守护进程失败: {e}"))?;
    if !status.status.success() {
        return Err(format!(
            "ccs daemon start 失败: {}",
            String::from_utf8_lossy(&status.stderr).trim()
        ));
    }
    let deadline = Instant::now() + Duration::from_secs(20);
    while Instant::now() < deadline {
        if ping() {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    Err("ccs 守护进程启动超时（查看 ccs 的 daemon.log）".to_string())
}

pub fn sessions() -> Result<Vec<Json>, String> {
    ensure_daemon()?;
    let request = Json::Obj(vec![("k".to_string(), Json::Str("ls".to_string()))]);
    let response = rpc(&request)?;
    if let Some(kind) = response.get("k").and_then(|v| v.as_str()) {
        if kind == "err" {
            return Err(response
                .get("msg")
                .and_then(|v| v.as_str())
                .unwrap_or("ccs 返回错误")
                .to_string());
        }
    }
    Ok(response
        .get("sessions")
        .and_then(|v| v.as_arr())
        .cloned()
        .unwrap_or_default())
}

pub fn restore(names: &[String]) -> Result<Json, String> {
    ensure_daemon()?;
    let mut request = vec![("k".to_string(), Json::Str("restore".to_string()))];
    if !names.is_empty() {
        request.push((
            "names".to_string(),
            Json::Arr(names.iter().map(|n| Json::Str(n.clone())).collect()),
        ));
    }
    rpc(&Json::Obj(request))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rpc_request_shape() {
        let request = Json::Obj(vec![("k".to_string(), Json::Str("ls".to_string()))]);
        assert_eq!(request.stringify(), r#"{"k":"ls"}"#);
    }
}
