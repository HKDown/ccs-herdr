//! 插件面板（跨平台、行式交互，无需终端原始模式）。

use crate::ccs;
use std::io::{self, Write};
use std::process::Command;

fn clear_screen() {
    // 现代终端（Windows Terminal / ConPTY、Linux、macOS）都支持 ANSI 清屏；
    // 老终端最多多打印几行，不影响功能。
    print!("\x1b[2J\x1b[H");
}

fn attach(name: &str) -> Result<(), String> {
    let bin = ccs::ccs_bin()
        .ok_or_else(|| "找不到 ccs 可执行文件（安装 ccs 或设置 CCS_BIN）".to_string())?;
    let status = Command::new(bin)
        .arg("attach")
        .arg(name)
        .status()
        .map_err(|e| format!("执行 ccs attach 失败: {e}"))?;
    let _ = status;
    Ok(())
}

pub fn run() -> Result<i32, String> {
    loop {
        let sessions = ccs::sessions()?;
        clear_screen();
        println!("ccs 会话（Herdr 面板）");
        println!("{}", "-".repeat(70));
        if sessions.is_empty() {
            println!("  (没有会话)  用 ccs new NAME -- claude 创建");
        }
        for (index, session) in sessions.iter().enumerate().take(9) {
            let name = session.get("name").and_then(|v| v.as_str()).unwrap_or("?");
            let status = session
                .get("status")
                .and_then(|v| v.as_str())
                .unwrap_or("?");
            let agent = session.get("agent").and_then(|v| v.as_str()).unwrap_or("-");
            let sid = session
                .get("session_id")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            println!(
                "  {}. {:<16} {:<8} {:<10} {}",
                index + 1,
                name,
                status,
                agent,
                sid
            );
        }
        println!("{}", "-".repeat(70));
        print!("  数字 = 在该窗格 attach | r = 刷新 | q = 退出 > ");
        io::stdout().flush().map_err(|e| format!("输出失败: {e}"))?;

        let mut line = String::new();
        let read = io::stdin()
            .read_line(&mut line)
            .map_err(|e| format!("读取输入失败: {e}"))?;
        if read == 0 {
            return Ok(0);
        }
        let input = line.trim().to_lowercase();
        if input == "q" || input == "quit" || input == "exit" {
            return Ok(0);
        }
        if input.is_empty() || input == "r" {
            continue;
        }
        if let Some(name) = input.strip_prefix("attach ") {
            attach(name.trim())?;
            continue;
        }
        if let Ok(index) = input.parse::<usize>() {
            if index >= 1 && index <= sessions.len() {
                let name = sessions[index - 1]
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                attach(&name)?;
            }
        }
    }
}
