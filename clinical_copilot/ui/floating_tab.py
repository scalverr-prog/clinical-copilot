"""Native macOS slide-in floating tab."""

import subprocess
import threading
import queue
import re
from pathlib import Path

import objc
import AppKit
from Foundation import NSObject
from PyObjCTools import AppHelper


PROJECT_DIR = Path(__file__).parent.parent.parent

# Import RAG store
try:
    from clinical_copilot.memory.rag_store import get_rag
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False
    get_rag = None

# Global state (avoids PyObjC method signature issues)
state = {
    'is_on': False,
    'is_expanded': False,
    'process': None,
    'output_queue': queue.Queue(),
    'window': None,
    'tab_btn': None,
    'term_scroll': None,
    'term_text': None,
    'content': None,
    'status_bar': None,
    'status_labels': {},
    'screen_w': 0,
    'screen_h': 0,
    'TAB_SIZE': 50,
    'EXPANDED_W': 500,
    'EXPANDED_H': 400,
    'STATUS_H': 30,
    'INPUT_H': 35,
    'input_field': None,
    'delegate': None,
    'clinical_context': [],  # Running memory of screen content
    'max_context_items': 50,  # Keep last 50 screen captures
    'current_patient': None,  # Current patient identifier
    'patient_contexts': {},   # Separate context per patient
}


def extract_patient_id(text):
    """Extract patient identifier from text."""
    import re

    # Common EHR patient identifier patterns
    patterns = [
        (r'(?i)MRN[:\s#]*(\d{5,10})', 'MRN'),
        (r'(?i)Patient\s*ID[:\s#]*(\d{5,10})', 'ID'),
        (r'(?i)Medical\s*Record[:\s#]*(\d{5,10})', 'MRN'),
        (r'(?i)Acct[:\s#]*(\d{5,10})', 'ACCT'),
        # Name pattern: Last, First or LAST, FIRST
        (r'(?i)Patient[:\s]+([A-Z][a-z]+,\s*[A-Z][a-z]+)', 'NAME'),
        (r'(?i)Name[:\s]+([A-Z][a-z]+,\s*[A-Z][a-z]+)', 'NAME'),
    ]

    for pattern, id_type in patterns:
        match = re.search(pattern, text)
        if match:
            return f"{id_type}:{match.group(1)}"

    return None


def check_patient_change(content):
    """Check if patient has changed and handle context switch."""
    patient_id = extract_patient_id(content)

    if patient_id and patient_id != state['current_patient']:
        old_patient = state['current_patient']

        # Save current context to old patient
        if old_patient and state['clinical_context']:
            state['patient_contexts'][old_patient] = state['clinical_context'].copy()

        # Switch to new patient
        state['current_patient'] = patient_id

        # Load existing context for new patient or start fresh
        if patient_id in state['patient_contexts']:
            state['clinical_context'] = state['patient_contexts'][patient_id].copy()
            return f"PATIENT CHANGED: Now viewing {patient_id} (restored {len(state['clinical_context'])} previous captures)"
        else:
            state['clinical_context'] = []
            return f"PATIENT CHANGED: Now viewing {patient_id} (new patient - context cleared)"

    return None


def add_to_clinical_context(content, source="screen"):
    """Add content to clinical context memory AND persistent RAG store."""
    if not content or len(content.strip()) < 20:
        return None

    # Check for patient change FIRST
    patient_change_msg = check_patient_change(content)

    timestamp = subprocess.run(
        ["date", "+%H:%M:%S"], capture_output=True, text=True
    ).stdout.strip()

    entry = {
        "time": timestamp,
        "source": source,
        "content": content[:2000],  # Limit size
        "patient": state['current_patient']
    }

    state['clinical_context'].append(entry)

    # Keep only recent items in working memory
    if len(state['clinical_context']) > state['max_context_items']:
        state['clinical_context'] = state['clinical_context'][-state['max_context_items']:]

    # Store in persistent RAG repository
    if RAG_AVAILABLE:
        try:
            rag = get_rag()
            rag.store(
                content=content[:2000],
                patient_id=state['current_patient'],
                source=source
            )
        except Exception as e:
            pass  # Don't fail if RAG has issues

    return patient_change_msg


def get_clinical_context_summary():
    """Get a summary of remembered clinical context."""
    current = state['current_patient'] or "No patient detected"
    patient_count = len(state['patient_contexts'])

    header = f"CURRENT PATIENT: {current}\n"
    header += f"Patients in memory: {patient_count + (1 if state['current_patient'] else 0)}\n"
    header += f"Context entries: {len(state['clinical_context'])}\n"
    header += "-" * 40 + "\n"

    if not state['clinical_context']:
        return header + "No clinical context captured yet."

    # Only show entries for current patient
    relevant = [
        e for e in state['clinical_context']
        if e.get('patient') == state['current_patient'] or e.get('patient') is None
    ][-10:]

    summary = [header]
    for entry in relevant:
        summary.append(f"[{entry['time']}] {entry['content'][:150]}...")

    return "\n".join(summary)


def query_rag_history(query: str, patient_id: str = None) -> str:
    """Query RAG for historical data."""
    if not RAG_AVAILABLE:
        return "RAG storage not available."

    try:
        rag = get_rag()
        patient = patient_id or state['current_patient']

        results = rag.query(
            query_text=query,
            patient_id=patient,
            n_results=10
        )

        if not results:
            return f"No historical data found for query: {query}"

        output = [f"Historical data for {patient or 'all patients'}:\n"]
        for r in results:
            meta = r['metadata']
            output.append(f"[{meta.get('date', '?')} {meta.get('time', '?')}] ({r['collection']})")
            output.append(f"  {r['content'][:200]}...")
            output.append("")

        return "\n".join(output)
    except Exception as e:
        return f"RAG query error: {e}"


def get_patient_timeline(days: int = 7) -> str:
    """Get chronological timeline for current patient."""
    if not RAG_AVAILABLE:
        return "RAG storage not available."

    patient = state['current_patient']
    if not patient:
        return "No patient currently selected."

    try:
        rag = get_rag()
        timeline = rag.get_patient_timeline(patient, days=days)

        if not timeline:
            return f"No timeline data for {patient} in last {days} days."

        output = [f"Timeline for {patient} (last {days} days):\n"]
        for entry in timeline:
            meta = entry['metadata']
            output.append(f"[{meta.get('date', '?')} {meta.get('time', '?')}] {meta.get('category', '?').upper()}")
            output.append(f"  {entry['content'][:150]}...")
            output.append("")

        return "\n".join(output)
    except Exception as e:
        return f"Timeline error: {e}"


def analyze_trends(query: str) -> str:
    """Analyze trends in historical data using LLM."""
    if not RAG_AVAILABLE:
        return "RAG storage not available."

    patient = state['current_patient']

    try:
        rag = get_rag()

        # Get historical data
        results = rag.query(
            query_text=query,
            patient_id=patient,
            n_results=20
        )

        if not results:
            return "Not enough historical data for trend analysis."

        # Build chronological context
        sorted_results = sorted(results, key=lambda x: x['metadata'].get('timestamp', ''))

        history_text = "\n\n".join([
            f"[{r['metadata'].get('date', '?')} {r['metadata'].get('time', '?')}]\n{r['content']}"
            for r in sorted_results
        ])

        prompt = f"""Analyze the following chronological clinical data for trends, changes, and clinically significant patterns.

PATIENT: {patient or 'Unknown'}
QUERY FOCUS: {query}

HISTORICAL DATA (oldest to newest):
{history_text}

Provide:
1. TREND ANALYSIS: Are values improving, worsening, or stable?
2. SIGNIFICANT CHANGES: Any notable changes between observations?
3. CLINICAL CONCERNS: Any patterns that warrant attention?
4. RECOMMENDATIONS: What should be monitored or addressed?

Be specific with dates/times when noting changes. If data is insufficient, say so."""

        return ask_llm(prompt)
    except Exception as e:
        return f"Trend analysis error: {e}"


def get_rag_stats() -> str:
    """Get RAG repository statistics."""
    if not RAG_AVAILABLE:
        return "RAG storage not available."

    try:
        rag = get_rag()
        stats = rag.get_stats()

        return f"""RAG Repository Stats:
  Encounters: {stats['encounters']}
  Notes: {stats['notes']}
  Labs: {stats['labs']}
  Medications: {stats['medications']}
  Total: {stats['total']}
  Storage: {stats['persist_dir']}"""
    except Exception as e:
        return f"Stats error: {e}"


def query_clinical_context(question):
    """Query the clinical context with LLM, using both working memory and RAG."""
    current_patient = state['current_patient'] or "Unknown Patient"

    # Build context from working memory
    relevant_entries = [
        e for e in state['clinical_context']
        if e.get('patient') == state['current_patient'] or e.get('patient') is None
    ]

    working_memory_text = ""
    if relevant_entries:
        working_memory_text = "\n\n".join([
            f"[{e['time']} - {e['source']}]\n{e['content']}"
            for e in relevant_entries[-10:]
        ])

    # Also get historical context from RAG
    historical_text = ""
    if RAG_AVAILABLE:
        try:
            rag = get_rag()
            rag_results = rag.query(
                query_text=question,
                patient_id=state['current_patient'],
                n_results=5
            )
            if rag_results:
                historical_text = "\n\n".join([
                    f"[{r['metadata'].get('date', '?')} - HISTORICAL]\n{r['content'][:500]}"
                    for r in rag_results
                ])
        except:
            pass

    if not working_memory_text and not historical_text:
        return f"No context captured for {current_patient}. Navigate through their chart first."

    combined_context = ""
    if working_memory_text:
        combined_context += f"CURRENT SESSION:\n{working_memory_text}\n\n"
    if historical_text:
        combined_context += f"HISTORICAL DATA:\n{historical_text}"

    prompt = f"""You are a clinical assistant. Based on the following clinical information, answer the question.

CURRENT PATIENT: {current_patient}

IMPORTANT SAFETY RULES:
- Only use information from the context below
- If information is not available, clearly state that
- Never guess or make up clinical information
- Note if information is from current session vs historical data
- If you see TRENDS (changes over time), highlight them

{combined_context}

QUESTION: {question}

Answer concisely and clinically. Compare current vs historical data when relevant. If information is missing, say "Based on available information for {current_patient}..." or "I don't see [X] - you may need to check [Y]"."""

    return ask_llm(prompt)


def execute_assistant_command(command):
    """Execute an assistant command."""
    cmd_lower = command.lower().strip()

    # Paste to Notes
    if "paste" in cmd_lower and "note" in cmd_lower:
        return paste_to_notes()

    # Open an app
    elif cmd_lower.startswith("open "):
        app_name = command[5:].strip()
        return open_app(app_name)

    # Copy last output
    elif "copy" in cmd_lower and ("output" in cmd_lower or "last" in cmd_lower):
        return copy_last_output()

    # Search
    elif cmd_lower.startswith("search "):
        query = command[7:].strip()
        return web_search(query)

    # Take screenshot
    elif "screenshot" in cmd_lower:
        return take_screenshot()

    # Show what's remembered
    elif "context" in cmd_lower or "memory" in cmd_lower or "remember" in cmd_lower:
        return get_clinical_context_summary()

    # Capture current screen to context
    elif "capture" in cmd_lower or "save this" in cmd_lower:
        return capture_current_screen()

    # Clear context
    elif "clear" in cmd_lower and "context" in cmd_lower:
        state['clinical_context'] = []
        return "Clinical context cleared."

    # RAG commands
    elif cmd_lower.startswith("history "):
        query = command[8:].strip()
        return query_rag_history(query)

    elif "timeline" in cmd_lower:
        days = 7
        if "month" in cmd_lower:
            days = 30
        elif "week" in cmd_lower:
            days = 7
        elif "today" in cmd_lower:
            days = 1
        return get_patient_timeline(days)

    elif cmd_lower.startswith("trend ") or cmd_lower.startswith("analyze "):
        query = command.split(" ", 1)[1] if " " in command else "overall"
        return analyze_trends(query)

    elif "rag stats" in cmd_lower or "storage stats" in cmd_lower:
        return get_rag_stats()

    # Clinical queries - check if it's a question about patient/chart
    elif any(word in cmd_lower for word in [
        "what", "when", "why", "how", "is the", "are the", "does", "did",
        "patient", "lab", "vitals", "medication", "diagnosis", "allergy",
        "result", "order", "note", "assessment", "plan", "history"
    ]):
        return query_clinical_context(command)

    # General LLM query
    else:
        return ask_llm(command)


def capture_current_screen():
    """Capture current screen content to context."""
    try:
        # Use screenpipe to get current screen text
        import urllib.request
        import json

        req = urllib.request.urlopen(
            "http://localhost:3030/search?content_type=ocr&limit=1",
            timeout=5
        )
        data = json.loads(req.read())

        if data and len(data) > 0:
            content = data[0].get("content", {}).get("text", "")
            if content:
                add_to_clinical_context(content, "manual_capture")
                return f"Captured {len(content)} chars to context."

        return "No screen content available to capture."
    except Exception as e:
        return f"Capture error: {e}"


def paste_to_notes():
    """Paste clipboard content to Apple Notes."""
    script = '''
    tell application "Notes"
        activate
        tell account "iCloud"
            set theNote to make new note at folder "Notes"
            set body of theNote to (the clipboard)
        end tell
    end tell
    '''
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
        return "Pasted to Notes"
    except Exception as e:
        return f"Error: {e}"


def open_app(app_name):
    """Open an application."""
    try:
        subprocess.run(["open", "-a", app_name], capture_output=True, timeout=5)
        return f"Opened {app_name}"
    except Exception as e:
        return f"Error opening {app_name}: {e}"


def copy_last_output():
    """Copy the last terminal output to clipboard."""
    try:
        text = state['term_text'].string()
        # Get last 500 chars
        last_text = text[-500:] if len(text) > 500 else text

        pb = AppKit.NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(last_text, AppKit.NSPasteboardTypeString)
        return "Copied to clipboard"
    except Exception as e:
        return f"Error: {e}"


def web_search(query):
    """Open web search."""
    import urllib.parse
    url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
    subprocess.run(["open", url], capture_output=True)
    return f"Searching: {query}"


def take_screenshot():
    """Take a screenshot."""
    try:
        subprocess.run(["screencapture", "-i", "-c"], timeout=30)
        return "Screenshot captured to clipboard"
    except Exception as e:
        return f"Error: {e}"


def ask_llm(prompt):
    """Ask the local LLM."""
    try:
        import urllib.request
        import json

        data = json.dumps({
            "model": "llama3:latest",
            "prompt": prompt,
            "stream": False
        }).encode()

        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=data,
            headers={"Content-Type": "application/json"}
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get("response", "No response")[:500]
    except Exception as e:
        return f"LLM Error: {e}"


def check_component_health():
    """Check health of all components."""
    import urllib.request
    import json

    health = {}

    # Check Screenpipe
    try:
        req = urllib.request.urlopen("http://localhost:3030/health", timeout=2)
        health['screenpipe'] = True
    except:
        health['screenpipe'] = False

    # Check Ollama
    try:
        req = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        health['ollama'] = True
    except:
        health['ollama'] = False

    # Check if copilot process is running
    result = subprocess.run(["pgrep", "-f", "clinical_copilot.main"], capture_output=True)
    health['copilot'] = result.returncode == 0

    return health


def update_status_display():
    """Update the status bar indicators."""
    if not state['status_labels']:
        return

    health = check_component_health()

    components = [
        ('screenpipe', 'Screen'),
        ('ollama', 'LLM'),
        ('copilot', 'Copilot'),
    ]

    for key, label in components:
        if key in state['status_labels']:
            is_ok = health.get(key, False)
            dot = "●" if is_ok else "○"
            color = AppKit.NSColor.greenColor() if is_ok else AppKit.NSColor.redColor()

            text = f"{dot} {label}"
            attrs = {
                AppKit.NSForegroundColorAttributeName: color,
                AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(10)
            }
            attr_str = AppKit.NSAttributedString.alloc().initWithString_attributes_(text, attrs)
            state['status_labels'][key].setAttributedStringValue_(attr_str)


def create_status_bar():
    """Create the status bar view."""
    bar_width = state['EXPANDED_W'] - state['TAB_SIZE']

    state['status_bar'] = AppKit.NSView.alloc().initWithFrame_(
        AppKit.NSMakeRect(0, state['EXPANDED_H'] - state['STATUS_H'], bar_width, state['STATUS_H'])
    )
    state['status_bar'].setWantsLayer_(True)
    state['status_bar'].layer().setBackgroundColor_(
        AppKit.NSColor.colorWithWhite_alpha_(0.2, 1).CGColor()
    )

    # Create status labels
    components = ['screenpipe', 'ollama', 'copilot']
    label_width = bar_width // 3

    for i, comp in enumerate(components):
        label = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(i * label_width + 10, 5, label_width - 20, 20)
        )
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setAlignment_(AppKit.NSTextAlignmentCenter)

        state['status_labels'][comp] = label
        state['status_bar'].addSubview_(label)

    update_status_display()


def set_btn_style(is_on):
    """Set button appearance."""
    btn = state['tab_btn']
    if is_on:
        color = AppKit.NSColor.colorWithRed_green_blue_alpha_(0.2, 0.5, 0.2, 1)
        text_color = AppKit.NSColor.greenColor()
    else:
        color = AppKit.NSColor.colorWithWhite_alpha_(0.2, 1)
        text_color = AppKit.NSColor.grayColor()

    btn.layer().setBackgroundColor_(color.CGColor())

    attrs = {
        AppKit.NSForegroundColorAttributeName: text_color,
        AppKit.NSFontAttributeName: AppKit.NSFont.boldSystemFontOfSize_(20)
    }
    title = AppKit.NSAttributedString.alloc().initWithString_attributes_("C", attrs)
    btn.setAttributedTitle_(title)


def append_text(text, color=None):
    """Append text to terminal."""
    if color is None:
        color = AppKit.NSColor.lightGrayColor()

    attrs = {
        AppKit.NSForegroundColorAttributeName: color,
        AppKit.NSFontAttributeName: AppKit.NSFont.fontWithName_size_("Monaco", 11)
    }
    attr_str = AppKit.NSAttributedString.alloc().initWithString_attributes_(text, attrs)
    state['term_text'].textStorage().appendAttributedString_(attr_str)
    state['term_text'].scrollToEndOfDocument_(None)


def clear_text():
    state['term_text'].setString_("")


def show_tab():
    """Show full tab button."""
    window = state['window']
    frame = window.frame()
    if frame.size.width < state['TAB_SIZE']:
        frame.origin.x = state['screen_w'] - state['TAB_SIZE']
        frame.size.width = state['TAB_SIZE']
        window.setFrame_display_animate_(frame, True, True)


def hide_tab():
    """Hide to thin sliver."""
    window = state['window']
    frame = window.frame()
    if frame.size.width > 8:
        frame.origin.x = state['screen_w'] - 8
        frame.size.width = 8
        window.setFrame_display_animate_(frame, True, True)


def create_input_field(delegate):
    """Create the command input field."""
    bar_width = state['EXPANDED_W'] - state['TAB_SIZE']

    state['input_field'] = AppKit.NSTextField.alloc().initWithFrame_(
        AppKit.NSMakeRect(5, 5, bar_width - 10, 25)
    )
    state['input_field'].setPlaceholderString_("Command: 'paste to note', 'open Safari', 'search ...'")
    state['input_field'].setFont_(AppKit.NSFont.systemFontOfSize_(12))
    state['input_field'].setBezeled_(True)
    state['input_field'].setBezelStyle_(AppKit.NSTextFieldRoundedBezel)
    state['input_field'].setTarget_(delegate)
    state['input_field'].setAction_(objc.selector(delegate.inputEntered_, signature=b'v@:@'))


def expand(delegate=None):
    """Expand to show terminal."""
    state['is_expanded'] = True
    window = state['window']

    # Create status bar if needed
    if state['status_bar'] is None:
        create_status_bar()

    # Create input field if needed
    if state['input_field'] is None and delegate:
        create_input_field(delegate)

    # Add status bar at top
    state['status_bar'].setFrame_(AppKit.NSMakeRect(
        0, state['EXPANDED_H'] - state['STATUS_H'],
        state['EXPANDED_W'] - state['TAB_SIZE'], state['STATUS_H']
    ))
    state['content'].addSubview_(state['status_bar'])

    # Add input field at bottom
    state['input_field'].setFrame_(AppKit.NSMakeRect(
        5, 5, state['EXPANDED_W'] - state['TAB_SIZE'] - 10, 25
    ))
    state['content'].addSubview_(state['input_field'])

    # Add terminal view in middle
    state['term_scroll'].setFrame_(AppKit.NSMakeRect(
        0, state['INPUT_H'],
        state['EXPANDED_W'] - state['TAB_SIZE'],
        state['EXPANDED_H'] - state['STATUS_H'] - state['INPUT_H']
    ))
    state['content'].addSubview_(state['term_scroll'])

    # Move button to top-right
    state['tab_btn'].setFrame_(AppKit.NSMakeRect(
        state['EXPANDED_W'] - state['TAB_SIZE'],
        state['EXPANDED_H'] - state['TAB_SIZE'],
        state['TAB_SIZE'], state['TAB_SIZE']
    ))

    # Resize window
    frame = window.frame()
    frame.origin.x = state['screen_w'] - state['EXPANDED_W']
    frame.origin.y = (state['screen_h'] - state['EXPANDED_H']) / 2
    frame.size.width = state['EXPANDED_W']
    frame.size.height = state['EXPANDED_H']
    window.setFrame_display_animate_(frame, True, True)


def collapse():
    """Collapse back to tab."""
    state['is_expanded'] = False
    window = state['window']

    state['term_scroll'].removeFromSuperview()
    if state['status_bar']:
        state['status_bar'].removeFromSuperview()
    if state['input_field']:
        state['input_field'].removeFromSuperview()

    state['tab_btn'].setFrame_(AppKit.NSMakeRect(
        0, 0, state['TAB_SIZE'], state['TAB_SIZE']
    ))

    frame = window.frame()
    frame.origin.x = state['screen_w'] - state['TAB_SIZE']
    frame.origin.y = (state['screen_h'] - state['TAB_SIZE']) / 2
    frame.size.width = state['TAB_SIZE']
    frame.size.height = state['TAB_SIZE']
    window.setFrame_display_animate_(frame, True, True)


def read_output():
    """Read process output in thread."""
    try:
        for line in state['process'].stdout:
            state['output_queue'].put(line)
    except:
        pass
    state['output_queue'].put(None)


def start_copilot(delegate):
    """Start copilot."""
    state['is_on'] = True
    state['delegate'] = delegate
    set_btn_style(True)
    expand(delegate)
    clear_text()
    append_text("Starting Clinical Copilot...\n", AppKit.NSColor.cyanColor())

    # Start screenpipe
    subprocess.run(["pkill", "-f", "screenpipe"], capture_output=True)
    subprocess.Popen(["/usr/local/bin/screenpipe", "--fps", "1"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Start copilot process with unbuffered output
    import os
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'

    state['process'] = subprocess.Popen(
        ["python3", "-u", "-m", "clinical_copilot.main", "on"],
        cwd=str(PROJECT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        universal_newlines=True,
        env=env
    )

    threading.Thread(target=read_output, daemon=True).start()
    delegate.pollOutput()


def stop_copilot():
    """Stop copilot."""
    append_text("\nStopping...\n", AppKit.NSColor.yellowColor())

    if state['process']:
        state['process'].terminate()
        state['process'] = None

    subprocess.run(["pkill", "-f", "clinical_copilot.main"], capture_output=True)
    subprocess.run(["pkill", "-f", "screenpipe"], capture_output=True)

    state['is_on'] = False
    set_btn_style(False)
    collapse()


class AppDelegate(NSObject):
    """App delegate."""

    def applicationDidFinishLaunching_(self, notification):
        screen = AppKit.NSScreen.mainScreen().frame()
        state['screen_w'] = screen.size.width
        state['screen_h'] = screen.size.height

        self.createWindow()
        self.startTracking()

    def createWindow(self):
        x = state['screen_w'] - state['TAB_SIZE']
        y = (state['screen_h'] - state['TAB_SIZE']) / 2

        state['window'] = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(x, y, state['TAB_SIZE'], state['TAB_SIZE']),
            AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered,
            False
        )

        window = state['window']
        window.setLevel_(AppKit.NSFloatingWindowLevel + 1)
        window.setBackgroundColor_(AppKit.NSColor.colorWithWhite_alpha_(0.15, 0.95))
        window.setOpaque_(False)
        window.setHasShadow_(True)
        window.setMovableByWindowBackground_(True)
        window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces |
            AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        state['content'] = AppKit.NSView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, state['TAB_SIZE'], state['TAB_SIZE'])
        )
        state['content'].setWantsLayer_(True)
        window.setContentView_(state['content'])

        state['tab_btn'] = AppKit.NSButton.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, state['TAB_SIZE'], state['TAB_SIZE'])
        )
        state['tab_btn'].setBezelStyle_(AppKit.NSBezelStyleTexturedSquare)
        state['tab_btn'].setBordered_(False)
        state['tab_btn'].setWantsLayer_(True)
        state['tab_btn'].setTarget_(self)
        state['tab_btn'].setAction_(objc.selector(self.tabClicked_, signature=b'v@:@'))
        set_btn_style(False)
        state['content'].addSubview_(state['tab_btn'])

        # Terminal view
        state['term_scroll'] = AppKit.NSScrollView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, state['EXPANDED_W'] - state['TAB_SIZE'], state['EXPANDED_H'])
        )
        state['term_scroll'].setHasVerticalScroller_(True)
        state['term_scroll'].setBorderType_(AppKit.NSNoBorder)
        state['term_scroll'].setBackgroundColor_(AppKit.NSColor.colorWithWhite_alpha_(0.1, 1))

        state['term_text'] = AppKit.NSTextView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, state['EXPANDED_W'] - state['TAB_SIZE'] - 20, 10000)
        )
        state['term_text'].setEditable_(False)
        state['term_text'].setBackgroundColor_(AppKit.NSColor.colorWithWhite_alpha_(0.1, 1))
        state['term_text'].setTextColor_(AppKit.NSColor.whiteColor())
        state['term_text'].setFont_(AppKit.NSFont.fontWithName_size_("Monaco", 11))
        state['term_scroll'].setDocumentView_(state['term_text'])

        window.orderFrontRegardless()

    def startTracking(self):
        # Hover tracking
        AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.05, self, objc.selector(self.checkHover_, signature=b'v@:@'), None, True
        )
        # Status update every 3 seconds
        AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            3.0, self, objc.selector(self.updateStatus_, signature=b'v@:@'), None, True
        )

    def updateStatus_(self, timer):
        if state['is_expanded']:
            threading.Thread(target=update_status_display, daemon=True).start()

        # Auto-capture screen content to clinical context when copilot is on
        if state['is_on']:
            threading.Thread(target=self.autoCapture, daemon=True).start()

    def autoCapture(self):
        """Auto-capture screen content to context."""
        try:
            import urllib.request
            import json

            req = urllib.request.urlopen(
                "http://localhost:3030/search?content_type=ocr&limit=1",
                timeout=3
            )
            data = json.loads(req.read())

            if data and len(data) > 0:
                content = data[0].get("content", {}).get("text", "")
                if content and len(content) > 50:
                    # Only add if it looks clinical
                    clinical_keywords = [
                        'patient', 'diagnosis', 'medication', 'lab', 'vital',
                        'mg', 'ml', 'assessment', 'plan', 'allergy', 'hx',
                        'chief complaint', 'dx', 'rx', 'prn', 'bid', 'tid',
                        'mrn', 'dob', 'admit'
                    ]
                    if any(kw in content.lower() for kw in clinical_keywords):
                        change_msg = add_to_clinical_context(content, "auto")
                        if change_msg:
                            # Alert user of patient change on main thread
                            AppHelper.callAfter(
                                lambda: append_text(f"\n⚠️ {change_msg}\n", AppKit.NSColor.orangeColor())
                            )
        except:
            pass

    def checkHover_(self, timer):
        mouse = AppKit.NSEvent.mouseLocation()
        frame = state['window'].frame()

        near_edge = mouse.x >= state['screen_w'] - 10
        over_window = AppKit.NSPointInRect(mouse, frame)

        if near_edge or over_window:
            if not state['is_expanded']:
                show_tab()
        else:
            if not state['is_expanded'] and not state['is_on']:
                hide_tab()

    def tabClicked_(self, sender):
        if state['is_on']:
            stop_copilot()
        else:
            start_copilot(self)

    def inputEntered_(self, sender):
        """Handle command input."""
        command = sender.stringValue()
        if command:
            append_text(f"\n> {command}\n", AppKit.NSColor.cyanColor())
            sender.setStringValue_("")

            # Run command in background
            def run_cmd():
                result = execute_assistant_command(command)
                # Update UI on main thread
                AppHelper.callAfter(lambda: append_text(f"{result}\n", AppKit.NSColor.greenColor()))

            threading.Thread(target=run_cmd, daemon=True).start()

    def pollOutput(self):
        try:
            while True:
                line = state['output_queue'].get_nowait()
                if line is None:
                    append_text("\n[Ended]\n", AppKit.NSColor.yellowColor())
                    return
                line = re.sub(r'\[/?[^\]]+\]', '', line)
                append_text(line)

                # Auto-capture clinical content to context
                if any(kw in line.lower() for kw in [
                    'patient', 'diagnosis', 'medication', 'lab', 'vital',
                    'assessment', 'plan', 'allergy', 'history', 'result'
                ]):
                    add_to_clinical_context(line, "monitor")

        except queue.Empty:
            pass

        if state['is_on']:
            self.performSelector_withObject_afterDelay_(
                objc.selector(self.pollOutput, signature=b'v@:'), None, 0.1
            )


def main():
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)

    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)

    app.activateIgnoringOtherApps_(True)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
