"""
Disklavier Activity Analysis

This module provides functions to analyze practice statistics from recorded MIDI files.
It parses the filename format to extract timestamps, durations, and note counts.
"""

import datetime
import re
import time
from typing import Optional, Tuple, Dict
from pathlib import Path
import calendar

from ..paths import iter_midi_recordings

try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    import numpy as np

    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


def parse_recording_filename(filepath: Path) -> Optional[Tuple[float, int, int]]:
    """
    Parse a recording filename to extract timestamp, duration, and note count.

    Expected format: 25JUN02-1144PM24-d0011-n000014.mid
    - 25JUN02-1144PM24: Timestamp (YYMmmDD-HHMMAMPMSS)
    - d0011: Duration in seconds
    - n000014: Number of notes

    Args:
        filepath: Path to the MIDI recording file

    Returns:
        Tuple of (timestamp_epoch, duration_seconds, note_count) or None if parsing fails
    """
    filename = filepath.stem  # Remove .mid extension

    # Regex to parse the filename format
    # Pattern: YYMmmDD-HHMMAMPMSS-dDDDD-nNNNNNN
    pattern = r"^(\d{2}[A-Z]{3}\d{2})-(\d{4}[AP]M\d{2})-d(\d{4})-n(\d{6})$"
    match = re.match(pattern, filename)

    if not match:
        return None

    date_part, time_part, duration_str, notes_str = match.groups()

    try:
        # Parse the timestamp
        # Format: 25JUN02-1144PM24 -> YYMmmDD-HHMMAMPMSS
        timestamp_str = f"{date_part}-{time_part}"

        # Convert to datetime object
        dt = datetime.datetime.strptime(timestamp_str, "%y%b%d-%I%M%p%S")

        # Convert to epoch time
        timestamp_epoch = dt.timestamp()

        # Parse duration and note count
        duration_seconds = int(duration_str)
        note_count = int(notes_str)

        return timestamp_epoch, duration_seconds, note_count

    except (ValueError, TypeError) as e:
        # Return None if parsing fails
        return None


def activity_over_period(
    start: Optional[float] = None, end: Optional[float] = None
) -> Tuple[int, float, int]:
    """
    Calculate practice statistics over a given time period.

    Args:
        start: Start time as epoch timestamp (time.time() format). If None, includes all recordings from beginning.
        end: End time as epoch timestamp (time.time() format). If None, includes all recordings until now.

    Returns:
        Tuple of (number_of_sessions, total_duration_seconds, total_notes)
    """
    session_count = 0
    total_duration = 0.0
    total_notes = 0

    # If no start time specified, use a very early date
    if start is None:
        start = 0.0

    # If no end time specified, use current time
    if end is None:
        end = time.time()

    # Iterate through all MIDI recordings
    for recording_path in iter_midi_recordings():
        # Parse the filename to extract metadata
        parsed = parse_recording_filename(recording_path)

        if parsed is None:
            # Skip files that don't match the expected format
            continue

        timestamp, duration, notes = parsed

        # Check if the recording falls within the specified time period
        if start <= timestamp <= end:
            session_count += 1
            total_duration += duration
            total_notes += notes

    return session_count, total_duration, total_notes


def get_recent_activity(days: int = 7) -> Tuple[int, float, int]:
    """
    Get practice statistics for the last N days.

    Args:
        days: Number of days to look back (default: 7)

    Returns:
        Tuple of (number_of_sessions, total_duration_seconds, total_notes)
    """
    end_time = time.time()
    start_time = end_time - (days * 24 * 60 * 60)  # days * seconds_per_day

    return activity_over_period(start_time, end_time)


def get_daily_stats(date: Optional[datetime.date] = None) -> Tuple[int, float, int]:
    """
    Get practice statistics for a specific day.

    Args:
        date: Date to analyze. If None, uses today.

    Returns:
        Tuple of (number_of_sessions, total_duration_seconds, total_notes)
    """
    if date is None:
        date = datetime.date.today()

    # Start of day
    start_dt = datetime.datetime.combine(date, datetime.time.min)
    start_time = start_dt.timestamp()

    # End of day
    end_dt = datetime.datetime.combine(date, datetime.time.max)
    end_time = end_dt.timestamp()

    return activity_over_period(start_time, end_time)


def format_duration(seconds: float) -> str:
    """
    Format duration in seconds to a human-readable string.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted duration string (e.g., "1h 23m 45s")
    """
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if secs > 0:
            return f"{hours}h {minutes}m {secs}s"
        else:
            return f"{hours}h {minutes}m"


def print_activity_summary(
    start: Optional[float] = None,
    end: Optional[float] = None,
    title: str = "Practice Activity Summary",
):
    """
    Print a formatted summary of practice activity.

    Args:
        start: Start time as epoch timestamp
        end: End time as epoch timestamp
        title: Title for the summary
    """
    sessions, duration, notes = activity_over_period(start, end)

    print(f"\n📊 {title}")
    print("=" * len(title))
    print(f"🎵 Sessions: {sessions}")
    print(f"⏰ Total practice time: {format_duration(duration)}")
    print(f"🎹 Total notes played: {notes:,}")

    if sessions > 0:
        avg_duration = duration / sessions
        avg_notes = notes / sessions
        print(
            f"📈 Average session: {format_duration(avg_duration)}, {avg_notes:.0f} notes"
        )

        # Calculate notes per minute
        if duration > 0:
            notes_per_minute = (notes / duration) * 60
            print(f"🎯 Notes per minute: {notes_per_minute:.1f}")


def get_daily_activity_data(days_back: int = 365) -> Dict[str, Tuple[int, float, int]]:
    """
    Get daily activity data for the last N days.

    Args:
        days_back: Number of days to look back

    Returns:
        Dictionary mapping date strings (YYYY-MM-DD) to (sessions, duration, notes) tuples
    """
    end_time = time.time()
    start_time = end_time - (days_back * 24 * 60 * 60)

    daily_data = {}

    # Initialize all days with zero activity
    current_date = datetime.date.fromtimestamp(start_time)
    end_date = datetime.date.fromtimestamp(end_time)

    while current_date <= end_date:
        daily_data[current_date.strftime("%Y-%m-%d")] = (0, 0.0, 0)
        current_date += datetime.timedelta(days=1)

    # Fill in actual activity data
    for recording_path in iter_midi_recordings():
        parsed = parse_recording_filename(recording_path)
        if parsed is None:
            continue

        timestamp, duration, notes = parsed

        if start_time <= timestamp <= end_time:
            # Convert timestamp to date string
            date_obj = datetime.date.fromtimestamp(timestamp)
            date_str = date_obj.strftime("%Y-%m-%d")

            if date_str in daily_data:
                existing_sessions, existing_duration, existing_notes = daily_data[
                    date_str
                ]
                daily_data[date_str] = (
                    existing_sessions + 1,
                    existing_duration + duration,
                    existing_notes + notes,
                )

    return daily_data


def create_summary_image(
    metric: str = "duration", include_header: bool = True, include_legend: bool = False
) -> Optional[bytes]:
    """
    Create a GitHub-style activity visualization for practice sessions.

    Args:
        metric: What to visualize - "duration", "sessions", or "notes"
        include_header: Whether to include summary header text
        include_legend: Whether to include the legend at bottom

    Returns:
        PNG image as bytes, or None if matplotlib is not available or error occurs
    """
    if not MATPLOTLIB_AVAILABLE:
        print(
            "❌ matplotlib is required for creating visualizations. Install with: pip install matplotlib"
        )
        return None

    try:
        import io

        # Fixed parameters for consistent output
        width = 16  # Make it fairly wide
        height = 3  # Compact height

        # Calculate date range for exactly 53 weeks ending with current week
        today = datetime.date.today()

        # Define special date
        piano_acquired_date = datetime.date(2025, 3, 22)

        # Find the start of the current week (most recent Sunday)
        days_since_sunday = (
            today.weekday() + 1
        ) % 7  # Convert Monday=0 to Sunday=0 system
        current_week_start = today - datetime.timedelta(days=days_since_sunday)

        # Go back 52 more weeks (53 total including current week)
        start_date = current_week_start - datetime.timedelta(weeks=52)
        end_date = today  # Only show up to today

        # Check if special date falls within our range
        show_piano_acquired = start_date <= piano_acquired_date <= end_date

        # Get daily activity data for the full range
        days_back = (today - start_date).days + 1
        daily_data = get_daily_activity_data(days_back)

        if not daily_data:
            print("❌ No activity data found")
            return None

        # Create figure and axis
        fig, ax = plt.subplots(figsize=(width, height))

        # Set up the grid parameters
        cell_size = 0.8
        cell_padding = 0.1

        # Build exactly 53 weeks starting from start_date
        weeks = []
        current_week = []
        grid_date = start_date

        for week_num in range(53):
            current_week = []

            # Add 7 days for this week
            for day_num in range(7):
                week_date = start_date + datetime.timedelta(
                    weeks=week_num, days=day_num
                )

                # Only include dates up to today
                if week_date <= today:
                    current_week.append(week_date)
                else:
                    current_week.append(None)  # Empty cell for future dates

            weeks.append(current_week)

        # Extract metric values and find min/max for color scaling
        metric_values = []
        for date_str, (sessions, duration, notes) in daily_data.items():
            if metric == "duration":
                metric_values.append(duration)
            elif metric == "sessions":
                metric_values.append(sessions)
            elif metric == "notes":
                metric_values.append(notes)

        if metric_values:
            max_value = max(metric_values)
            min_value = min(metric_values)
        else:
            max_value = min_value = 0

        # Color scheme (similar to GitHub)
        colors = ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"]

        def get_color_for_value(value):
            if max_value == 0:
                return colors[0]

            # Normalize value to 0-1
            normalized = value / max_value if max_value > 0 else 0

            if normalized == 0:
                return colors[0]
            elif normalized <= 0.25:
                return colors[1]
            elif normalized <= 0.5:
                return colors[2]
            elif normalized <= 0.75:
                return colors[3]
            else:
                return colors[4]

        # Draw the grid
        for week_idx, week in enumerate(weeks):
            for day_idx, date in enumerate(week):
                x = week_idx * (cell_size + cell_padding)
                # day_idx 0 = Sunday (top), day_idx 6 = Saturday (bottom)
                y = (6 - day_idx) * (
                    cell_size + cell_padding
                )  # Reverse Y so Sunday is at top

                if date is None:
                    # Empty cell for future dates - don't draw anything
                    continue
                else:
                    # Check if this is the special Piano Acquired date
                    if date == piano_acquired_date:
                        color = "#ff0000"  # Red for Piano Acquired
                    else:
                        # Normal activity coloring
                        date_str = date.strftime("%Y-%m-%d")
                        if date_str in daily_data:
                            sessions, duration, notes = daily_data[date_str]
                            if metric == "duration":
                                value = duration
                            elif metric == "sessions":
                                value = sessions
                            elif metric == "notes":
                                value = notes
                            else:
                                value = 0
                        else:
                            value = 0

                        color = get_color_for_value(value)

                # Draw cell
                rect = patches.Rectangle(
                    (x, y),
                    cell_size,
                    cell_size,
                    linewidth=1,
                    edgecolor="white",
                    facecolor=color,
                )
                ax.add_patch(rect)

        # Add month labels
        month_positions = {}
        for week_idx, week in enumerate(weeks):
            if week[0] is not None:  # First day of week exists
                month = week[0].month
                year = week[0].year
                month_key = f"{year}-{month:02d}"

                if month_key not in month_positions:
                    month_positions[month_key] = week_idx * (cell_size + cell_padding)

        # Add month labels at the top
        header_y = 7 * (cell_size + cell_padding) + 0.2

        for month_key, x_pos in month_positions.items():
            year, month = month_key.split("-")
            month_name = calendar.month_abbr[int(month)]
            ax.text(
                x_pos + cell_size / 2,
                header_y,
                month_name,
                ha="center",
                va="bottom",
                fontsize=16,
            )

        # Add header summary if requested
        if include_header:
            # Calculate total activity for the year shown
            total_sessions = 0
            total_duration = 0.0
            total_notes = 0

            for date_str, (sessions, duration, notes) in daily_data.items():
                total_sessions += sessions
                total_duration += duration
                total_notes += notes

            # Format duration in hours
            hours = total_duration / 3600
            if hours >= 1:
                duration_text = f"{hours:.1f} hours"
            else:
                minutes = total_duration / 60
                duration_text = f"{minutes:.0f} minutes"

            # Create header text
            header_text = f"In the last year, practiced for {duration_text}, played {total_notes:,} notes"

            # Left-justify the header above the grid
            ax.text(
                -0.8,  # Left align with the grid
                header_y + 1.2,  # More space between header and months
                header_text,
                ha="left",
                va="bottom",
                fontsize=18,  # Slightly larger than other text
            )

        # Add day labels - only Mon, Wed, Fri (same size as months)
        # In our grid: Sunday=0(top), Monday=1, Tuesday=2, Wednesday=3, Thursday=4, Friday=5, Saturday=6(bottom)
        day_labels = [
            "",
            "Mon",
            "",
            "Wed",
            "",
            "Fri",
            "",
        ]  # Sunday, Mon, Tue, Wed, Thu, Fri, Sat
        for day_idx, label in enumerate(day_labels):
            if label:
                y = (6 - day_idx) * (cell_size + cell_padding) + cell_size / 2
                ax.text(-0.3, y, label, ha="right", va="center", fontsize=16)

        # Add legend conditionally
        if include_legend:
            legend_x = 53 * (cell_size + cell_padding) - 5  # Move legend closer to grid
            legend_y = -0.8  # More vertical padding

            # Add Piano Acquired legend if the date is visible
            if show_piano_acquired:
                # Draw red square for Piano Acquired - add more spacing from Less
                piano_legend_x = legend_x - 12  # Further left for better spacing
                rect = patches.Rectangle(
                    (piano_legend_x, legend_y - cell_size / 2),
                    cell_size,
                    cell_size,
                    linewidth=1,
                    edgecolor="white",
                    facecolor="#ff0000",
                )
                ax.add_patch(rect)
                ax.text(
                    piano_legend_x + cell_size + 0.1,
                    legend_y,
                    "Piano Acquired",
                    ha="left",
                    va="center",
                    fontsize=16,
                )

            # Position Less/More legend with proper spacing for perfect squares
            less_more_start = legend_x - 2
            ax.text(
                less_more_start - 0.3,
                legend_y,
                "Less",
                ha="right",
                va="center",
                fontsize=16,
            )

            for i, color in enumerate(colors):
                rect = patches.Rectangle(
                    (
                        less_more_start + i * (cell_size + cell_padding),
                        legend_y - cell_size / 2,
                    ),  # Use same spacing as grid
                    cell_size,
                    cell_size,
                    linewidth=1,
                    edgecolor="lightgray",
                    facecolor=color,
                )
                ax.add_patch(rect)

            ax.text(
                less_more_start + len(colors) * (cell_size + cell_padding) + 0.1,
                legend_y,
                "More",
                ha="left",
                va="center",
                fontsize=16,
            )

        # Set axis properties
        ax.set_xlim(-0.8, 53 * (cell_size + cell_padding))  # Exactly 53 columns

        # Adjust Y limits based on header and legend
        y_min = -1.4 if include_legend else -0.8  # Added bottom margin
        y_max = (
            9.0 * (cell_size + cell_padding)  # More space for header
            if include_header
            else 7.5 * (cell_size + cell_padding)
        )

        ax.set_ylim(y_min, y_max)
        ax.set_aspect("equal")
        ax.axis("off")

        # Save to bytes instead of file
        buffer = io.BytesIO()
        plt.tight_layout()
        plt.savefig(
            buffer,
            format="png",
            dpi=300,
            bbox_inches="tight",
            facecolor="white",
            edgecolor="none",
        )
        plt.close()

        # Get the PNG bytes
        buffer.seek(0)
        png_bytes = buffer.getvalue()
        buffer.close()

        return png_bytes

    except Exception as e:
        print(f"❌ Error creating visualization: {e}")
        return None


def main():
    """Command line interface for activity analysis."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Disklavier Practice Activity Analysis"
    )
    parser.add_argument(
        "--days",
        "-d",
        type=int,
        default=7,
        help="Number of recent days to analyze (default: 7)",
    )
    parser.add_argument(
        "--today", action="store_true", help="Show only today's activity"
    )
    parser.add_argument("--all", action="store_true", help="Show all-time activity")
    parser.add_argument(
        "--visualize",
        "-v",
        action="store_true",
        help="Create a visual activity chart (requires matplotlib)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="practice_activity.png",
        help="Output file for visualization (default: practice_activity.png)",
    )
    parser.add_argument(
        "--metric",
        "-m",
        type=str,
        choices=["duration", "sessions", "notes"],
        default="duration",
        help="Metric to visualize: duration, sessions, or notes (default: duration)",
    )
    parser.add_argument(
        "--no-header", action="store_true", help="Hide the summary header"
    )
    parser.add_argument(
        "--legend", action="store_true", help="Show the legend at bottom"
    )

    args = parser.parse_args()

    # Handle visualization request
    if args.visualize:
        png_bytes = create_summary_image(
            metric=args.metric,
            include_header=not args.no_header,
            include_legend=args.legend,
        )
        if png_bytes:
            # Save bytes to file
            with open(args.output, "wb") as f:
                f.write(png_bytes)
            print(f"✓ Visualization created with {args.metric} metric")
            print(f"📊 Activity chart saved to: {args.output}")
        else:
            print("❌ Failed to create visualization")
        return

    # Handle regular text reports
    if args.today:
        sessions, duration, notes = get_daily_stats()
        start_dt = datetime.datetime.combine(datetime.date.today(), datetime.time.min)
        end_dt = datetime.datetime.combine(datetime.date.today(), datetime.time.max)
        print_activity_summary(
            start_dt.timestamp(), end_dt.timestamp(), title="Today's Practice"
        )
    elif args.all:
        print_activity_summary(title="All-Time Practice Activity")
    else:
        sessions, duration, notes = get_recent_activity(args.days)
        start_time = time.time() - (args.days * 24 * 60 * 60)
        print_activity_summary(
            start_time, None, title=f"Last {args.days} Days Practice Activity"
        )


if __name__ == "__main__":
    main()
