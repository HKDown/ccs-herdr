//! Herdr 插件目录定位与链接。

use crate::herdr;
use crate::paths;
use std::path::PathBuf;

/// 插件目录查找顺序：
/// 1. CCS_HERDR_PLUGIN_DIR
/// 2. 可执行文件旁边的 plugin/ 或 herdr-plugin/
/// 3. 源码树（编译时的 CARGO_MANIFEST_DIR/plugin，仅开发机存在）
/// 4. 数据目录下的 plugin/
pub fn plugin_dir() -> PathBuf {
    if let Some(v) = std::env::var_os("CCS_HERDR_PLUGIN_DIR") {
        if !v.is_empty() {
            let path = PathBuf::from(v);
            if path.join("herdr-plugin.toml").is_file() {
                return path;
            }
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            for name in ["plugin", "herdr-plugin"] {
                let candidate = dir.join(name);
                if candidate.join("herdr-plugin.toml").is_file() {
                    return candidate;
                }
            }
        }
    }
    if let Some(manifest) = option_env!("CARGO_MANIFEST_DIR") {
        let candidate = PathBuf::from(manifest).join("plugin");
        if candidate.join("herdr-plugin.toml").is_file() {
            return candidate;
        }
    }
    paths::data_dir().join("plugin")
}

pub fn link() -> Result<String, String> {
    let dir = plugin_dir();
    if !dir.join("herdr-plugin.toml").is_file() {
        return Err(format!("找不到插件目录: {}", dir.display()));
    }
    let args = vec![
        "plugin".to_string(),
        "link".to_string(),
        dir.to_string_lossy().to_string(),
    ];
    let (code, stdout, stderr) = herdr::run(&args)?;
    let text = format!("{stdout}{stderr}").trim().to_string();
    if code != 0 {
        return Err(format!("herdr plugin link 失败（exit {code}）: {text}"));
    }
    Ok(if text.is_empty() {
        format!("已链接插件: {}", dir.display())
    } else {
        text
    })
}
