"""
Explainer - Human-readable output formatting

Formats verdicts for terminal, logs, and notifications.
"""

import logging
from datetime import datetime
from typing import List, Optional

from colorama import Fore, Back, Style, init

from models import (
    DetectionVerdict,
    DetectorState,
    ConfidenceLevel,
    SignalDetection
)

# Initialize colorama for cross-platform colored output
init(autoreset=True)

logger = logging.getLogger(__name__)


class ExplainerFormatter:
    """
    Formats detection verdicts into human-readable explanations.
    
    Provides multiple output formats:
    - Rich terminal output (with colors)
    - Plain text (for logs)
    - JSON (for programmatic use)
    - Slack/markdown (for notifications)
    """
    
    def __init__(self, use_colors: bool = True):
        """
        Initialize formatter.
        
        Args:
            use_colors: Whether to use ANSI colors in output
        """
        self.use_colors = use_colors
    
    def format_verdict(self, verdict: DetectionVerdict) -> str:
        """
        Format a detection verdict into rich terminal output.
        
        This is the primary output format for terminal display.
        
        Args:
            verdict: Detection verdict to format
        
        Returns:
            Formatted string with colors and structure
        """
        lines = []
        
        # Header
        lines.append(self._format_header(verdict))
        lines.append("")
        
        # Symptoms section
        if verdict.symptoms:
            lines.append(self._format_section("Symptoms", verdict.symptoms))
            lines.append("")
        
        # Illusions section (why alerts didn't fire)
        if verdict.illusions:
            lines.append(self._format_section(
                "Why alerts didn't fire", 
                verdict.illusions
            ))
            lines.append("")
        
        # Masking signals section
        if verdict.masking_signals:
            lines.append(self._format_section(
                "Masking signals detected", 
                verdict.masking_signals
            ))
            lines.append("")
        
        # Impact assessment
        if verdict.likely_impact:
            lines.append(self._format_impact(verdict.likely_impact))
            lines.append("")
        
        # Suggested actions
        if verdict.suggested_actions:
            lines.append(self._format_actions(verdict.suggested_actions))
            lines.append("")
        
        # Footer with metadata
        lines.append(self._format_footer(verdict))
        
        return "\n".join(lines)
    
    def format_plain(self, verdict: DetectionVerdict) -> str:
        """
        Format verdict as plain text (no colors).
        
        Useful for log files and systems that don't support ANSI colors.
        
        Args:
            verdict: Detection verdict to format
        
        Returns:
            Plain text formatted string
        """
        # Temporarily disable colors
        original_colors = self.use_colors
        self.use_colors = False
        
        result = self.format_verdict(verdict)
        
        # Restore color setting
        self.use_colors = original_colors
        
        return result
    
    def format_slack(self, verdict: DetectionVerdict) -> dict:
        """
        Format verdict for Slack notification.
        
        Returns a Slack Block Kit formatted message.
        
        Args:
            verdict: Detection verdict to format
        
        Returns:
            Slack message payload (dict)
        """
        blocks = []
        
        # Header block
        color = self._get_state_color_slack(verdict.state)
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"! {verdict.state.value.upper()}",
                "emoji": True
            }
        })
        
        # Summary
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{verdict.summary}*"
            }
        })
        
        blocks.append({"type": "divider"})
        
        # Symptoms
        if verdict.symptoms:
            symptom_text = "\n".join([
                f"• {s.description}" for s in verdict.symptoms
            ])
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Symptoms:*\n{symptom_text}"
                }
            })
        
        # Impact
        if verdict.likely_impact:
            impact_text = "\n".join([
                f"• {i}" for i in verdict.likely_impact
            ])
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Likely impact:*\n{impact_text}"
                }
            })
        
        # Actions
        if verdict.suggested_actions:
            action_text = "\n".join([
                f"{i+1}. {a}" for i, a in enumerate(verdict.suggested_actions[:3])
            ])
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Suggested actions:*\n{action_text}"
                }
            })
        
        # Footer with metadata
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"Service: `{verdict.service}` | "
                        f"Confidence: {verdict.confidence.value} | "
                        f"Detected: {verdict.detected_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                    )
                }
            ]
        })
        
        return {
            "attachments": [
                {
                    "color": color,
                    "blocks": blocks
                }
            ]
        }
    
    def _format_header(self, verdict: DetectionVerdict) -> str:
        """Format the header section."""
        state_emoji = self._get_state_emoji(verdict.state)
        state_text = verdict.state.value.replace('_', '-').upper()
        
        if self.use_colors:
            color = self._get_state_color_ansi(verdict.state)
            confidence_color = self._get_confidence_color(verdict.confidence)
            
            header = (
                f"{color}{'━' * 80}\n"
                f"{state_emoji} {state_text} DETECTED "
                f"({confidence_color}{verdict.confidence.value.upper()} Confidence{color})\n"
                f"{'━' * 80}{Style.RESET_ALL}"
            )
        else:
            header = (
                f"{'=' * 80}\n"
                f"{state_emoji} {state_text} DETECTED "
                f"({verdict.confidence.value.upper()} Confidence)\n"
                f"{'=' * 80}"
            )
        
        return header
    
    def _format_section(
        self, 
        title: str, 
        signals: List[SignalDetection]
    ) -> str:
        """Format a section with signals."""
        lines = []
        
        if self.use_colors:
            lines.append(f"{Fore.CYAN}{Style.BRIGHT}{title}:{Style.RESET_ALL}")
        else:
            lines.append(f"{title}:")
        
        for signal in signals:
            bullet = "  •" if self.use_colors else "  *"
            lines.append(f"{bullet} {signal.description}")
            
            # Add metadata if present and significant
            if signal.metadata:
                if 'percentage_change' in signal.metadata:
                    pct = signal.metadata['percentage_change']
                    if pct != 0:
                        lines.append(f"    (change: {pct:+.1f}%)")
        
        return "\n".join(lines)
    
    def _format_impact(self, impacts: List[str]) -> str:
        """Format the impact assessment section."""
        lines = []
        
        if self.use_colors:
            lines.append(
                f"{Fore.YELLOW}{Style.BRIGHT}Likely user impact:{Style.RESET_ALL}"
            )
        else:
            lines.append("Likely user impact:")
        
        for impact in impacts:
            bullet = "  •" if self.use_colors else "  *"
            lines.append(f"{bullet} {impact}")
        
        return "\n".join(lines)
    
    def _format_actions(self, actions: List[str]) -> str:
        """Format the suggested actions section."""
        lines = []
        
        if self.use_colors:
            lines.append(
                f"{Fore.GREEN}{Style.BRIGHT}Suggested investigation steps:{Style.RESET_ALL}"
            )
        else:
            lines.append("Suggested investigation steps:")
        
        for i, action in enumerate(actions, 1):
            lines.append(f"  {i}. {action}")
        
        return "\n".join(lines)
    
    def _format_footer(self, verdict: DetectionVerdict) -> str:
        """Format the footer with metadata."""
        signal_count = verdict.total_signals
        timestamp = verdict.detected_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        
        if self.use_colors:
            footer = (
                f"{Fore.LIGHTBLACK_EX}"
                f"{'─' * 80}\n"
                f"Service: {verdict.service} | "
                f"Signals: {signal_count} | "
                f"Confidence: {verdict.confidence_score:.2f} | "
                f"Detected: {timestamp}\n"
                f"{'━' * 80}"
                f"{Style.RESET_ALL}"
            )
        else:
            footer = (
                f"{'-' * 80}\n"
                f"Service: {verdict.service} | "
                f"Signals: {signal_count} | "
                f"Confidence: {verdict.confidence_score:.2f} | "
                f"Detected: {timestamp}\n"
                f"{'=' * 80}"
            )
        
        return footer
    
    def _get_state_emoji(self, state: DetectorState) -> str:
        """Get emoji for detector state."""
        emoji_map = {
            DetectorState.GREEN_BUT_DEAD: "!",
            DetectorState.DEGRADED: "!",
            DetectorState.HEALTHY: "✓",
            DetectorState.UNKNOWN: "❓"
        }
        return emoji_map.get(state, "❓")
    
    def _get_state_color_ansi(self, state: DetectorState) -> str:
        """Get ANSI color for detector state."""
        if not self.use_colors:
            return ""
        
        color_map = {
            DetectorState.GREEN_BUT_DEAD: Fore.RED + Style.BRIGHT,
            DetectorState.DEGRADED: Fore.YELLOW + Style.BRIGHT,
            DetectorState.HEALTHY: Fore.GREEN + Style.BRIGHT,
            DetectorState.UNKNOWN: Fore.LIGHTBLACK_EX
        }
        return color_map.get(state, "")
    
    def _get_state_color_slack(self, state: DetectorState) -> str:
        """Get Slack color for detector state."""
        color_map = {
            DetectorState.GREEN_BUT_DEAD: "danger",  # Red
            DetectorState.DEGRADED: "warning",       # Yellow
            DetectorState.HEALTHY: "good",           # Green
            DetectorState.UNKNOWN: "#666666"         # Gray
        }
        return color_map.get(state, "#666666")
    
    def _get_confidence_color(self, confidence: ConfidenceLevel) -> str:
        """Get ANSI color for confidence level."""
        if not self.use_colors:
            return ""
        
        color_map = {
            ConfidenceLevel.CRITICAL: Fore.RED + Style.BRIGHT,
            ConfidenceLevel.HIGH: Fore.YELLOW + Style.BRIGHT,
            ConfidenceLevel.MEDIUM: Fore.CYAN,
            ConfidenceLevel.LOW: Fore.LIGHTBLACK_EX
        }
        return color_map.get(confidence, "")


def format_detection_log(verdict: DetectionVerdict) -> str:
    """
    Format verdict for structured logging.
    
    Creates a compact, single-line log entry suitable for log aggregation systems.
    
    Args:
        verdict: Detection verdict
    
    Returns:
        Structured log line
    """
    return (
        f"detection_verdict "
        f"service={verdict.service} "
        f"state={verdict.state.value} "
        f"confidence={verdict.confidence.value} "
        f"confidence_score={verdict.confidence_score:.2f} "
        f"signals={verdict.total_signals} "
        f"symptoms={len(verdict.symptoms)} "
        f"illusions={len(verdict.illusions)} "
        f"masking={len(verdict.masking_signals)}"
    )
