# To launch: `uvicorn app_inksync:app --reload`
from app_params import model_card, NO_LEFT_MENU, ENABLE_CHAT, ENABLE_MARKERS, ENABLE_LOCAL, ENABLE_WARN_VERIFY_AUDIT
from fastapi import FastAPI, Request, Form, Depends, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from utils_inksync import create_starter_document, get_user_documents
from model_recommender import RecommendationEngine
from utils_trace import run_suggestion_tracing
import utils_misc, json, os, time, pytz
from bson.objectid import ObjectId
from collections import Counter
from datetime import datetime

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/js", StaticFiles(directory="static/js"), name="js")
app.mount("/css", StaticFiles(directory="static/css"), name="css")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

utils_misc.DoublePrint("logs/app.log")
API_LOG_FILE = "logs/api_log.jsonl"
engine = RecommendationEngine(model_card=model_card)

# 用户ID和日志处理
@app.middleware("http")
async def set_user_id(request: Request, call_next):
    user_id = request.cookies.get('inksync_uid')
    if user_id is not None and not user_id.startswith("UU"):
        user_id = None
    request.state.start_ts = time.time()
    request.state.skip_log = False
    request.state.doc_id = -1
    if user_id is None:
        new_user_id = "UU%s" % str(ObjectId())
        with open("data/users.jsonl", "a") as f:
            f.write(json.dumps({"id": new_user_id, "creation_timestamp": datetime.now().isoformat()}) + "\n")
        request.state.user_id = new_user_id
        response = await call_next(request)
        response.set_cookie('inksync_uid', new_user_id, max_age=60 * 60 * 24 * 90)
        return response
    else:
        request.state.user_id = user_id
        response = await call_next(request)
        response.set_cookie('inksync_uid', user_id, max_age=60 * 60 * 24 * 90)
        return response


# Set the cookie in the after_request hook
@app.middleware("http")
async def log_request(request: Request, call_next):
    response = await call_next(request)
    if not request.state.skip_log:
        print("[%s] [User %s] %s" % (datetime.now(tz=pytz.timezone('America/New_York')).strftime("%Y-%m-%d %H:%M:%S"), request.state.user_id, request.url.path))
        entry = {"timestamp": datetime.now().isoformat(), "user_id": request.state.user_id, "endpoint": request.url.path, "duration": time.time() - request.state.start_ts, "doc_id": request.state.doc_id}
        with open(API_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    return response


# 主页和文档页面
@app.get("/", response_class=HTMLResponse)
async def app_inksync_homepage(request: Request, no_menu: str = "false"):
    documents = get_user_documents(request.state.user_id)
    no_menu_class = "no_menu" if (no_menu != "false" or NO_LEFT_MENU) else ""
    return templates.TemplateResponse("main.html", {"request": request, "documents": documents, "active_doc": {}, "homepage": True, "no_menu_class": no_menu_class, "hidden_systems_class": ""})

@app.get("/doc/{doc_id}", response_class=HTMLResponse)
@app.get("/doc/{doc_id}/review", response_class=HTMLResponse)
async def app_inksync_docpage(request: Request, doc_id: str, no_menu: str = "false"):
    no_menu_class = "no_menu" if (no_menu != "false" or NO_LEFT_MENU) else ""
    documents = get_user_documents(request.state.user_id)
    id2doc = {d["id"]: d for d in documents}
    active_doc = {}
    if len(documents) > 0:
        if doc_id is None or doc_id not in id2doc:
            doc_id = documents[0]["id"]
            request.state.doc_id = doc_id
        active_doc = id2doc[doc_id]
    hidden_systems_class = ""
    if not ENABLE_CHAT:
        hidden_systems_class += " no_chat"
    if not ENABLE_MARKERS:
        hidden_systems_class += " no_markers"
    if not ENABLE_LOCAL:
        hidden_systems_class += " no_local"
    if not ENABLE_WARN_VERIFY_AUDIT:
        hidden_systems_class += " no_verify"
    return templates.TemplateResponse("main.html", {"request": request, "documents": documents, "active_doc": active_doc, "no_menu_class": no_menu_class, "hidden_systems_class": hidden_systems_class})


@app.api_route("/new_doc", methods=["GET", "POST"], response_class=RedirectResponse)
async def app_new_doc(request: Request):
    new_doc = create_starter_document(request.state.user_id, initial_text="")
    doc_id = new_doc["id"]
    request.state.doc_id = doc_id
    with open(f"documents/{doc_id}.json", "w") as f:
        json.dump(new_doc, f, indent=4)
    return RedirectResponse(url=f"/doc/{doc_id}")


@app.post("/save_document_title", response_class=JSONResponse)
async def app_save_document_title(request: Request):
    doc_id = request.form["doc_id"]
    request.state.doc_id = doc_id
    new_title = request.form["new_title"]

    if os.path.exists("documents/%s.json" % doc_id):
        with open("documents/%s.json" % doc_id) as f:
            doc = json.load(f)
            doc["name"] = new_title
        with open("documents/%s.json" % doc_id, "w") as f:
            json.dump(doc, f, indent=4)

    return JSONResponse(content={"success": True})


@app.post("/change_view_mode", response_class=JSONResponse)
async def app_change_view_mode(request: Request):
    doc_id = request.form["doc_id"]
    request.state.doc_id = doc_id
    view_mode = request.form["view_mode"]
    if view_mode not in ["Hover", "Inline"]:
        view_mode = "Hover"

    if os.path.exists("documents/%s.json" % doc_id):
        with open("documents/%s.json" % doc_id) as f:
            doc = json.load(f)
        if "view_mode_history" not in doc:
            doc["view_mode_history"] = []
        doc["view_mode"] = view_mode
        doc["view_mode_history"].append({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "view_mode": view_mode})
        with open("documents/%s.json" % doc_id, "w") as f:
            json.dump(doc, f, indent=4)
        return JSONResponse(content={"success": True})
    return JSONResponse(content={"success": False})


@app.post("/change_markers_disabled", response_class=JSONResponse)
async def app_change_markers_disabled(request: Request):
    doc_id = request.form["doc_id"]
    request.state.doc_id = doc_id
    markers_disabled = request.form["markers_disabled"]
    if markers_disabled not in ["0", "1"]:
        markers_disabled = "0"

    if os.path.exists("documents/%s.json" % doc_id):
        with open("documents/%s.json" % doc_id) as f:
            doc = json.load(f)
        doc["markers_disabled"] = markers_disabled
        with open("documents/%s.json" % doc_id, "w") as f:
            json.dump(doc, f, indent=4)
        return JSONResponse(content={"success": True})
    return JSONResponse(content={"success": False})


@app.post("/delete_doc/{doc_id}", response_class=RedirectResponse)
async def app_delete_doc(request: Request, doc_id: str):
    request.state.doc_id = doc_id
    if os.path.exists("documents/%s.json" % doc_id):
        # check if we're the owner_id
        with open("documents/%s.json" % doc_id) as f:
            doc = json.load(f)
            if doc.get("owner_user_id", -1) != request.state.user_id:
                return RedirectResponse(url="/")

        # remove file
        os.remove("documents/%s.json" % doc_id)
        
    return RedirectResponse(url="/")


@app.post("/save_marker", response_class=JSONResponse)
async def app_save_marker(request: Request):
    doc_id = request.form["doc_id"]
    request.state.doc_id = doc_id
    marker = json.loads(request.form["marker"])

    if os.path.exists("documents/%s.json" % doc_id):
        with open("documents/%s.json" % doc_id) as f:
            doc = json.load(f)
            if "description" not in marker:
                marker["description"] = ""
            if "strike_style" not in marker:
                marker["strike_style"] = "solid"
            if "strike_color" not in marker:
                marker["strike_color"] = "#E31E3E"

            if "id" not in marker: # we insert it
                marker["id"] = str(ObjectId())
                doc["markers"].append(marker)
            else: # we update it
                for i, m in enumerate(doc["markers"]):
                    if m["id"] == marker["id"]:
                        doc["markers"][i] = marker
                        break
            marker["visible"] = "visible"

        with open("documents/%s.json" % doc_id, "w") as f:
            json.dump(doc, f, indent=4)

        return JSONResponse(content={"success": True, "markers": doc["markers"]})
    return JSONResponse(content={"success": False})


@app.post("/delete_marker", response_class=JSONResponse)
async def app_delete_marker(request: Request):
    doc_id = request.form["doc_id"]
    request.state.doc_id = doc_id
    marker_id = request.form["marker_id"]

    if os.path.exists("documents/%s.json" % doc_id):
        with open("documents/%s.json" % doc_id) as f:
            doc = json.load(f)
            for marker in doc["markers"]:
                if marker["id"] == marker_id:
                    marker["deleted"] = 1

        with open("documents/%s.json" % doc_id, "w") as f:
            json.dump(doc, f, indent=4)

        return JSONResponse(content={"success": True, "markers": doc["markers"]})
    return JSONResponse(content={"success": False})


@app.post("/change_marker_visibility", response_class=JSONResponse)
async def app_change_marker_visibility(request: Request):
    doc_id = request.form["doc_id"]
    request.state.doc_id = doc_id
    marker_ids = request.form["marker_ids"].split(",")
    new_visible = request.form["visible"]

    if os.path.exists("documents/%s.json" % doc_id):
        with open("documents/%s.json" % doc_id) as f:
            doc = json.load(f)
            for marker in doc["markers"]:
                if marker["id"] in marker_ids:
                    marker["visible"] = new_visible

        with open("documents/%s.json" % doc_id, "w") as f:
            json.dump(doc, f, indent=4)

        return JSONResponse(content={"success": True})
    return JSONResponse(content={"success": False})


@app.post("/save_doc_state", response_class=JSONResponse)
async def app_save_doc_state(request: Request):
    doc_id = request.form["doc_id"]
    request.state.doc_id = doc_id
    new_text = request.form["new_text"]
    user_rejected_suggestion_ids = json.loads(request.form["user_rejected_suggestion_ids"])
    user_autodel_suggestion_ids = json.loads(request.form["user_autodel_suggestion_ids"])
    user_accepted_suggestion_ids = json.loads(request.form["user_accepted_suggestion_ids"])
    previous_suggestions = json.loads(request.form["current_suggestions"])
    active_comments = json.loads(request.form["current_comments"])

    if not os.path.exists("documents/%s.json" % doc_id):
        return JSONResponse(content={"success": False})

    with open("documents/%s.json" % doc_id, "r") as f:
        doc = json.load(f)
        all_suggestions = doc["suggestions"]

    latest_anchor_map = {sug["id"]: sug["anchor_idx"] for sug in previous_suggestions}

    for sug in all_suggestions:
        if sug["id"] in user_rejected_suggestion_ids:
            sug["action"] = "deleted_by_user"
        if sug["id"] in user_accepted_suggestion_ids:
            sug["action"] = "accepted_by_user"
            print(">> Accepted regular edit")
        if sug["id"] in user_autodel_suggestion_ids:
            sug["action"] = "autodel_by_user"
        if sug["id"] in latest_anchor_map:
            sug["anchor_idx"] = latest_anchor_map[sug["id"]]

    if len(user_accepted_suggestion_ids) > 0:
        # Check the brainstorm edits
        for sugg_id in user_accepted_suggestion_ids:
            for brainstorm in doc["brainstorms"]:
                if sugg_id in [s["id"] for s in brainstorm["suggestions"]]:
                    brainstorm["accepted_id"] = sugg_id
                    print(">> Accepted brainstorm edit.")

    # Need to also update the comments in case either the anchor_idx or the selection_text has changed
    comment_map = {c["id"]: c for c in doc["comments"]}
    for comment in active_comments:
        if comment["id"] in comment_map:
            old_comm = comment_map[comment["id"]]
            # skip if already archive
            if old_comm["status"] != "active":
                continue

            old_comm["anchor_idx"] = comment["anchor_idx"]
            old_comm["selection_text"] = comment["selection_text"]
            old_comm["status"] = comment["status"] # In case it was auto deleted

    accepted_type_counts = Counter([(s["suggestion_type"], "accepted") for s in all_suggestions if s["id"] in user_accepted_suggestion_ids] + [(s["suggestion_type"], "rejected") for s in all_suggestions if s["id"] in user_rejected_suggestion_ids])
    for (sug_type, acc_rej), count in accepted_type_counts.most_common():
        if sug_type == "CHAT":
            plural = "suggestions" if count > 1 else "suggestion"
            doc["conversation"].append({"id": str(ObjectId()), "sender": "system", "message": "%d chat %s %s." % (count, plural, acc_rej), "timestamp": datetime.now().isoformat()})
        elif sug_type.startswith("COMMENT_"):
            comment_id = sug_type.split("_")[1]
            if comment_id in comment_map:
                old_comm = comment_map[comment_id]
                plural = "suggestions" if count > 1 else "suggestion"
                old_comm["conversation"].append({"id": str(ObjectId()), "sender": "system", "message": "%d comment %s %s." % (count, plural, acc_rej), "timestamp": datetime.now().isoformat()})

    suggestion_ids = [s["id"] for s in all_suggestions if "action" not in s]
    doc["document_history"].append({"text": new_text, "suggestion_ids": suggestion_ids, "timestamp": datetime.now().isoformat(), "accepted_suggestion_ids": user_accepted_suggestion_ids}) # Last bit for tracability

    # Redo the write, and only return once the write is done
    with open("documents/%s.json" % doc_id, "w") as f:
        json.dump(doc, f, indent=4)
        f.flush()
        f.close()
    return JSONResponse(content={"success": True})


@app.post("/get_markers_suggestions", response_class=JSONResponse)
async def app_get_markers_suggestions(request: Request):
    doc_id = request.form["doc_id"]
    request.state.doc_id = doc_id
    if not os.path.exists("documents/%s.json" % doc_id):
        return JSONResponse(content={"suggestions": []})

    with open("documents/%s.json" % doc_id, "r") as f:
        doc = json.load(f)
    text = doc["document_history"][-1]["text"]

    markers = doc["markers"]
    focus_marker_id = request.form["focus_marker_id"]

    active_markers = [m for m in markers if m.get("deleted", 0) == 0]
    is_focus_query = focus_marker_id != "" and focus_marker_id in [m["id"] for m in active_markers]

    new_suggestions = []
    if len(text) >= 20:
        if is_focus_query:
            active_markers = [m for m in active_markers if m["id"] == focus_marker_id]
        new_suggestions = engine.get_marker_suggestions(text, active_markers, document_id=doc_id)

    #  In case things have moved
    with open("documents/%s.json" % doc_id, "r") as f:
        doc = json.load(f)

    doc["suggestions"] += new_suggestions
    active_suggestions = [sug for sug in doc["suggestions"] if "action" not in sug]

    with open("documents/%s.json" % doc_id, "w") as f:
        json.dump(doc, f, indent=4)
    return JSONResponse(content={"suggestions": active_suggestions})


@app.post("/send_chat", response_class=JSONResponse)
async def app_send_chat(request: Request):
    doc_id = request.form["doc_id"]
    user_id = request.state.user_id
    request.state.doc_id = doc_id
    message = request.form["message"]
    print("[Doc id: %s] [Chat message: %s]" % (doc_id, message))

    if os.path.exists("documents/%s.json" % doc_id):
        with open("documents/%s.json" % doc_id) as f:
            doc = json.load(f)
            doc["conversation"].append({
                "id": str(ObjectId()),
                "sender": "user",
                "message": message,
                "timestamp": datetime.now().isoformat()
            })

        for sug in doc["suggestions"]:
            if sug["suggestion_type"] == "CHAT" and "action" not in sug:
                sug["action"] = "deleted_by_model_chat"

        last_document = doc["document_history"][-1]['text']
        response = engine.generate_chat_response(last_document, doc["conversation"], document_id=doc_id)

        print("[Doc id: %s] [Chat; %d suggestions] [Message: %s]" % (doc_id, len(response["suggestions"]), response["reply"]))
        doc["conversation"].append({"id": str(ObjectId()), "sender": "assistant", "message": response["reply"], "timestamp": datetime.now().isoformat(), "suggestion_ids": [s["id"] for s in response["suggestions"]]})

        all_suggestions = doc["suggestions"] + response["suggestions"]

        active_suggestions = sorted([s for s in all_suggestions if "action" not in s], key=lambda x: x["suggestion_type"] != "CHAT")

        # Save the document history (with new suggestions) and the suggestions
        doc["suggestions"] = all_suggestions

        with open("documents/%s.json" % doc_id, "w") as f:
            json.dump(doc, f, indent=4)
        return JSONResponse(content={"success": True, "conversation": doc["conversation"], "suggestions": active_suggestions})
    else:
        return JSONResponse(content={"success": False})


@app.post("/clear_chat", response_class=JSONResponse)
async def app_clear_chat(request: Request):
    doc_id = request.form["doc_id"]
    request.state.doc_id = doc_id

    if os.path.exists("documents/%s.json" % doc_id):
        with open("documents/%s.json" % doc_id) as f:
            doc = json.load(f)
            # Mark all the messages as "clear": 1
            for msg in doc["conversation"]:
                msg["clear"] = 1

            # Re-add the first message in
            doc["conversation"].append({"id": str(ObjectId()), "sender": "assistant", "message": "Don't hesitate to ask for edit suggestions in the chat.", "timestamp": datetime.now().isoformat()})

            # Dismiss all chat suggestions that were still pending
            for sug in doc["suggestions"]:
                if sug["suggestion_type"] == "CHAT" and "action" not in sug:
                    sug["action"] = "deleted_by_user"

        with open("documents/%s.json" % doc_id, "w") as f:
            json.dump(doc, f, indent=4)

        return JSONResponse(content={"success": True, "conversation": doc["conversation"]})
    else:
        return JSONResponse(content={"success": False})


@app.post("/retry_chat", response_class=JSONResponse)
async def app_retry_chat(request: Request):
    doc_id = request.form["doc_id"]
    request.state.doc_id = doc_id

    if os.path.exists("documents/%s.json" % doc_id):
        with open("documents/%s.json" % doc_id) as f:
            doc = json.load(f)
            
        # Mark the last assistant message as retry: 1
        assistant_messages = [msg for msg in doc["conversation"] if msg["sender"] == "assistant"]
        del_suggestion_ids = []
        if len(assistant_messages) > 0:
            del_suggestion_ids = assistant_messages[-1]["suggestion_ids"]
            assistant_messages[-1]["retry"] = 1

        # Dismiss all chat suggestions that were still pending
        for sug in doc["suggestions"]:
            if "action" not in sug and sug["id"] in del_suggestion_ids:
                sug["action"] = "deleted_by_user_retry"

        last_document = doc["document_history"][-1]['text']
        response = engine.generate_chat_response(last_document, doc["conversation"], document_id=doc_id)

        print("[Doc id: %s] [Chat; %d suggestions] [Message: %s]" % (doc_id, len(response["suggestions"]), response["reply"]))
        doc["conversation"].append({"id": str(ObjectId()), "sender": "assistant", "message": response["reply"], "timestamp": datetime.now().isoformat(), "suggestion_ids": [s["id"] for s in response["suggestions"]]})

        all_suggestions = doc["suggestions"] + response["suggestions"]
        active_suggestions = sorted([s for s in all_suggestions if "action" not in s], key=lambda x: x["suggestion_type"] != "CHAT")

        with open("documents/%s.json" % doc_id, "w") as f:
            json.dump(doc, f, indent=4)

        return JSONResponse(content={"success": True, "conversation": doc["conversation"], "suggestions": active_suggestions})
    else:
        return JSONResponse(content={"success": False})


@app.post("/start_brainstorm", response_class=JSONResponse)
async def app_start_brainstorm(request: Request):
    doc_id = request.form["doc_id"]
    request.state.doc_id = doc_id
    cursor_line_index = int(request.form["cursor_line_index"])
    cursor_position = int(request.form["cursor_position"])
    selection_text = request.form["selection_text"]

    if os.path.exists("documents/%s.json" % doc_id):
        with open("documents/%s.json" % doc_id) as f:
            doc = json.load(f)

            latest_doc = doc["document_history"][-1]["text"]

            response = engine.generate_brainstorm(latest_doc, latest_doc, cursor_line_index, cursor_position, selection_text, document_id=doc_id)
            suggestions = response["suggestions"]

            doc["brainstorms"].append({
                "id": str(ObjectId()),
                "cursor_line_index": cursor_line_index,
                "cursor_position": cursor_position,
                "selection_text": selection_text,
                "timestamp": datetime.now().isoformat(),
                "suggestions": suggestions
            })

        with open("documents/%s.json" % doc_id, "w") as f:
            json.dump(doc, f, indent=4)

        return JSONResponse(content={"brainstorm_suggestions": suggestions})
    return JSONResponse(content={"brainstorm_suggestions": []})


@app.post("/start_comment", response_class=JSONResponse)
async def app_start_comment(request: Request):
    doc_id = request.form["doc_id"]
    request.state.doc_id = doc_id
    anchor_idx = int(request.form["anchor_idx"])
    selection_text = request.form["selection_text"]

    if os.path.exists("documents/%s.json" % doc_id):
        with open("documents/%s.json" % doc_id) as f:
            active_comment_id = str(ObjectId())
            doc = json.load(f)
            doc["comments"].append({
                "id": active_comment_id,
                "anchor_idx": anchor_idx,
                "selection_text": selection_text,
                "creation_timestamp": datetime.now().isoformat(),
                "conversation": [],
                "accepted_suggestion_ids": [],
                "status": "active",
            })

        with open("documents/%s.json" % doc_id, "w") as f:
            json.dump(doc, f, indent=4)

        return JSONResponse(content={"comments": doc["comments"], "active_comment_id": active_comment_id})
    return JSONResponse(content={"comments": [], "active_comment_id": ""})


@app.post("/send_comment_reply", response_class=JSONResponse)
async def app_send_comment_chat(request: Request):
    doc_id = request.form["doc_id"]
    request.state.doc_id = doc_id
    user_id = request.state.user_id
    comment_id = request.form["comment_id"]
    message = request.form["message"]

    print("[Doc id: %s] [Message: %s]" % (doc_id, message))

    if os.path.exists("documents/%s.json" % doc_id):
        with open("documents/%s.json" % doc_id) as f:
            doc = json.load(f)

        comments = [c for c in doc["comments"] if c["id"] == comment_id]
        if len(comments) == 0:
            return JSONResponse(content={"comments": doc["comment"]})

        comment = comments[0]
        comment["conversation"].append({"id": str(ObjectId()), "sender": "user", "message": message, "timestamp": datetime.now().isoformat()})

        last_document = doc["document_history"][-1]['text']
        response = engine.generate_comment_response(last_document, last_document, comment["conversation"], comment["selection_text"], comment["anchor_idx"], document_id=doc_id)
        print("[Doc id: %s] [Comment Response; %d suggestions] [Message: %s]" % (doc_id, len(response["suggestions"]), response["reply"]))

        # In the document's suggestions, delete previous comment suggestions
        for sug in doc["suggestions"]:
            if sug["suggestion_type"] == "COMMENT_%s" % comment_id and "action" not in sug:
                sug["action"] = "deleted_by_model_comment"

        for sug in response["suggestions"]:
            sug["suggestion_type"] = "COMMENT_%s" % comment_id

        all_suggestions = doc["suggestions"] + response["suggestions"]
        new_suggestions = [sug for sug in all_suggestions if "action" not in sug]

        doc["suggestions"] = all_suggestions

        comment["conversation"].append({"id": str(ObjectId()), "sender": "assistant", "message": response["reply"], "timestamp": datetime.now().isoformat(), "suggestion_ids": [s["id"] for s in response["suggestions"]]})

        with open("documents/%s.json" % doc_id, "w") as f:
            json.dump(doc, f, indent=4)

        return JSONResponse(content={"success": True, "comments": doc["comments"], "suggestions": new_suggestions})

    return JSONResponse(content={"success": False, "comments": [], "suggestions": []})


@app.post("/archive_comment", response_class=JSONResponse)
async def app_archive_comment(request: Request):
    doc_id = request.form["doc_id"]
    request.state.doc_id = doc_id
    comment_id = request.form["comment_id"]

    if os.path.exists("documents/%s.json" % doc_id):
        with open("documents/%s.json" % doc_id) as f:
            doc = json.load(f)
            for comment in doc["comments"]:
                if comment["id"] == comment_id:
                    comment["status"] = "archived"
                    comment["archive_timestamp"] = datetime.now().isoformat()

            for sug in doc["suggestions"]:
                if sug["suggestion_type"] == "COMMENT_%s" % comment_id and "action" not in sug:
                    sug["action"] = "deleted_by_comment_archive"

        with open("documents/%s.json" % doc_id, "w") as f:
            json.dump(doc, f, indent=4)

        new_suggestions = [sug for sug in doc["suggestions"] if "action" not in sug]
        return JSONResponse(content={"comments": doc["comments"], "suggestions": new_suggestions})
    return JSONResponse(content={"comments": []})


@app.post("/verify_suggestion/{doc_id}/{suggestion_id}", response_class=JSONResponse)
async def app_verify_suggestion(request: Request, doc_id: str, suggestion_id: str):
    request.state.doc_id = doc_id
    if os.path.exists("documents/%s.json" % doc_id):
        with open("documents/%s.json" % doc_id) as f:
            doc = json.load(f)
        sug = [s for s in doc["suggestions"] if s["id"] == suggestion_id]
        if len(sug) > 0:
            sug = sug[0]
            latest_text = doc["document_history"][-1]["text"]
            if "verification_queries" not in sug or len(sug["verification_queries"]) == 0:
                response = engine.generate_verify_response(latest_text, sug, document_id=doc_id)
                sug["verification_queries"] = [{"id": str(ObjectId()), "query": q, "visited": "0"} for q in response]

        with open("documents/%s.json" % doc_id, "w") as f:
            json.dump(doc, f, indent=4)

        return JSONResponse(content={"success": True, "suggestion": sug})
    return JSONResponse(content={"success": False, "suggestion": {}})


@app.get("/verify_suggestion/{doc_id}/{suggestion_id}/{verification_query_id}", response_class=RedirectResponse)
async def app_verify_suggestion_query(request: Request, doc_id: str, suggestion_id: str, verification_query_id: str):
    request.state.doc_id = doc_id
    if os.path.exists("documents/%s.json" % doc_id):
        with open("documents/%s.json" % doc_id) as f:
            doc = json.load(f)
        sug = [s for s in doc["suggestions"] if s["id"] == suggestion_id]
        if len(sug) > 0:
            sug = sug[0]
            for q in sug["verification_queries"]:
                if q["id"] == verification_query_id:
                    q["visited"] = "1"
                    with open("documents/%s.json" % doc_id, "w") as f:
                        json.dump(doc, f, indent=4)
                    return RedirectResponse(url=f"https://www.google.com/search?q=%s" % q["query"]) # Redirect to Google search with query q["query"]

    return JSONResponse(content={"success": False, "suggestion": {}})


@app.post("/mark_verification_result", response_class=JSONResponse)
async def app_mark_verification_result(request: Request):
    doc_id = request.form["doc_id"]
    request.state.doc_id = doc_id
    sugg_id = request.form["sugg_id"]
    result = request.form["result"]
    if result not in ["verified", "incorrect", "not_sure"]:
        result = ""

    if os.path.exists("documents/%s.json" % doc_id):
        with open("documents/%s.json" % doc_id) as f:
            doc = json.load(f)
        sug = [s for s in doc["suggestions"] if s["id"] == sugg_id]
        if len(sug) > 0:
            sug = sug[0]
            sug["verif_result"] = result
            print("[User ID: %s] [Suggestion Is Accurate: %s] [Verif Result: %s]" % (request.state.user_id, sug.get("is_inaccurate", "-1"), result))

        with open("documents/%s.json" % doc_id, "w") as f:
            json.dump(doc, f, indent=4)

        return JSONResponse(content={"success": True, "suggestion": sug})
    return JSONResponse(content={"success": False, "suggestion": {}})


@app.post("/get_review_doc", response_class=JSONResponse)
async def app_get_review_doc(request: Request):
    doc_id = request.form["doc_id"]
    request.state.doc_id = doc_id
    if os.path.exists("documents/%s.json" % doc_id):
        with open("documents/%s.json" % doc_id) as f:
            doc = json.load(f)

        suggestions = doc["suggestions"]
        tracks = run_suggestion_tracing(doc["document_history"], suggestions, final_cleanup=True)
        sug_ids = set([t["suggestion_id"] for t in tracks])

        suggestions = [s for s in suggestions if s["id"] in sug_ids]

        sug_counts = Counter([t["suggestion_id"] for t in tracks])
        suggestions = sorted(suggestions, key=lambda x: sug_counts[x["id"]], reverse=True)
        final_version = doc["document_history"][-1]["text"]
        return JSONResponse(content={"review_doc": {"suggestions": suggestions, "tracks": tracks, "final_version": final_version.rstrip()}})
    return JSONResponse(content={"review_doc": []})


@app.post("/interpret_shortcut", response_class=JSONResponse)
async def app_interpret_shortcut(request: Request):
    doc_id = request.form["doc_id"]
    request.state.doc_id = doc_id
    shortcut_query = request.form["query"]
    if os.path.exists("documents/%s.json" % doc_id):

        with open("documents/%s.json" % doc_id, "r") as f:
            doc = json.load(f)
        if doc is None:
            return JSONResponse(content={"success": False})
        latest_text = doc["document_history"][-1]["text"]

        response = engine.generate_shortcut_interpretation(latest_text, shortcut_query, document_id=doc_id)
        return JSONResponse(content={"success": True, "response": response})
    return JSONResponse(content={"success": False})
