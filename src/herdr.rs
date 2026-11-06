//! Herdr CLI 封装（通过 HERDR_BIN_PATH 或 PATH 找到 herdr）。

use crate::json::{self, Json};
use crate::paths;
use std::path::PathBuf;
use std::process::Command;

pub fn herdr_bin() -> Option<PathBuf> {
    if let Some(v) = std::env::var_os("HERDR_BIN_PATH") {
        if !v.is_empty() {
            let path = PathBuf::from(v);
            if path.is_file() {
                return Some(path);
            }
        }
    }
    paths::which("herdr")
}

pub fn run(args: &[String]) -> Result<(i32, String, String), String> {
    let bin = herdr_bin().ok_or_else(|| {
        "未找到 herdr 可执行文件（PATH 或 HERDR_BIN_PATH）。先安装 Herdr".to_string()
    })?;
    let output = Command::new(bin)
        .args(args)
        .output()
        .map_err(|e| format!("执行 herdr 失败: {e}"))?;
    Ok((
        output.status.code().unwrap_or(-1),
        String::from_utf8_lossy(&output.stdout).to_string(),
        String::from_utf8_lossy(&output.stderr).to_string(),
    ))
}

pub fn run_json(args: &[String]) -> Result<(i32, Json, String), String> {
    let (code, stdout, stderr) = run(args)?;
    let value = if stdout.trim().is_empty() {
        Json::Null
    } else {
        json::parse_or_null(&stdout)
    };
    Ok((code, value, stderr))
}

pub fn result_of(value: &Json) -> &Json {
    value.get("result").unwrap_or(value)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn result_unwraps() {
        let value = json::parse(r#"{"result":{"pane_id":"p1"}}"#).unwrap();
        assert_eq!(
            result_of(&value).get("pane_id").and_then(|v| v.as_str()),
            Some("p1")
        );
        let plain = json::parse(r#"{"pane_id":"p2"}"#).unwrap();
        assert_eq!(
            result_of(&plain).get("pane_id").and_then(|v| v.as_str()),
            Some("p2")
        );
    }
}
