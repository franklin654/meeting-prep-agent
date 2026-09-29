export interface paths {
    "/api/meetings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Meetings
         * @description Meetings with attendees and brief status, soonest first.
         */
        get: operations["list_meetings_api_meetings_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/meetings/{meeting_id}/notes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Submit Notes
         * @description Save the transcript, create an ingest job and run ingest after the response.
         *
         *     The background task gets `session_factory`, not the request session, which is
         *     closed when the request ends. The meeting is marked done by ingest itself.
         */
        post: operations["submit_notes_api_meetings__meeting_id__notes_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Job
         * @description `pending`, `done` (with the learned summary) or `failed` (with the error code).
         */
        get: operations["get_job_api_jobs__job_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/meetings/{meeting_id}/brief": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Read Brief
         * @description The stored brief; 404 when none exists or a later ingest made it stale.
         */
        get: operations["read_brief_api_meetings__meeting_id__brief_get"];
        put?: never;
        /**
         * Create Brief
         * @description Generate a fresh brief for the meeting, replacing any stored one for this mode.
         */
        post: operations["create_brief_api_meetings__meeting_id__brief_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/briefs/{brief_id}/feedback": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Post Feedback
         * @description Store the feedback row, retain one preference sentence, return the new profile.
         */
        post: operations["post_feedback_api_briefs__brief_id__feedback_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/style": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Style
         * @description The style profile derived from every feedback row.
         */
        get: operations["get_style_api_style_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/contacts/{contact_id}/timeline": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Contact Timeline
         * @description Everything memory knows about a contact, newest meeting first, deduplicated, max 30.
         */
        get: operations["contact_timeline_api_contacts__contact_id__timeline_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health
         * @description Liveness stub.
         *
         *     Full dependency checks (Hindsight, DB) land with the memory and db gateways
         *     (T06, T07); for now this only proves the API process is up.
         */
        get: operations["health_api_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** Brief */
        Brief: {
            /** Id */
            id: string;
            /** Meeting Id */
            meeting_id: string;
            /**
             * Mode
             * @enum {string}
             */
            mode: "memory" | "no_memory";
            /**
             * Generated At
             * Format: date-time
             */
            generated_at: string;
            /** Sections */
            sections: components["schemas"]["BriefSection"][];
            /** Facts Used */
            facts_used: number;
            /** Preferences Applied */
            preferences_applied: string[];
        };
        /** BriefItem */
        BriefItem: {
            /** Id */
            id: string;
            /** Text */
            text: string;
            severity: components["schemas"]["Severity"];
            /** Contact Ids */
            contact_ids: string[];
            /** Citations */
            citations: components["schemas"]["Citation"][];
        };
        /** BriefSection */
        BriefSection: {
            key: components["schemas"]["SectionKey"];
            /** Title */
            title: string;
            /** Items */
            items: components["schemas"]["BriefItem"][];
            /**
             * Collapsed
             * @default false
             */
            collapsed: boolean;
        };
        /** Citation */
        Citation: {
            source_type: components["schemas"]["SourceType"];
            /** Meeting Id */
            meeting_id: string | null;
            /** Meeting Date */
            meeting_date: string | null;
            /** Label */
            label: string;
            /** Quote */
            quote: string | null;
            /** Memory Id */
            memory_id: string | null;
        };
        /** ContactRef */
        ContactRef: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Role */
            role: string | null;
        };
        /** ContactTimeline */
        ContactTimeline: {
            contact: components["schemas"]["ContactRef"];
            /** Entries */
            entries: components["schemas"]["TimelineEntry"][];
        };
        /**
         * FactKind
         * @enum {string}
         */
        FactKind: "commitment" | "objection" | "personal" | "deal_fact" | "competitor";
        /** FeedbackRequest */
        FeedbackRequest: {
            section: components["schemas"]["SectionKey"];
            /**
             * Action
             * @enum {string}
             */
            action: "up" | "down" | "more" | "less" | "collapsed";
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** JobAccepted */
        JobAccepted: {
            /** Job Id */
            job_id: string;
        };
        /** JobStatus */
        JobStatus: {
            /** Id */
            id: string;
            /** Kind */
            kind: string;
            /**
             * Status
             * @enum {string}
             */
            status: "pending" | "done" | "failed";
            learned?: components["schemas"]["LearnedSummary"] | null;
            /** Error */
            error?: string | null;
        };
        /** LearnedSummary */
        LearnedSummary: {
            /** Facts */
            facts: string[];
            /** New Commitments */
            new_commitments: number;
            /** Closed Commitments */
            closed_commitments: number;
            /** Alerts */
            alerts: string[];
        };
        /** MeetingSummary */
        MeetingSummary: {
            /** Id */
            id: string;
            /** Account Id */
            account_id: string;
            /** Account Name */
            account_name: string;
            /** Title */
            title: string;
            /**
             * Scheduled At
             * Format: date-time
             */
            scheduled_at: string;
            /** Status */
            status: string;
            /** Attendees */
            attendees: components["schemas"]["ContactRef"][];
            /** Brief Ready */
            brief_ready: boolean;
        };
        /** NotesRequest */
        NotesRequest: {
            /** Transcript */
            transcript: string;
        };
        /**
         * SectionKey
         * @enum {string}
         */
        SectionKey: "attendees" | "where_left_off" | "open_commitments" | "unresolved_objections" | "personal_touchpoints" | "agenda" | "watch_outs" | "alerts" | "your_questions";
        /**
         * Severity
         * @enum {string}
         */
        Severity: "info" | "warning" | "critical";
        /**
         * SourceType
         * @enum {string}
         */
        SourceType: "meeting" | "ledger" | "mental_model" | "ask";
        /** StyleProfile */
        StyleProfile: {
            /** Section Order */
            section_order: components["schemas"]["SectionKey"][];
            /** Hidden Sections */
            hidden_sections: components["schemas"]["SectionKey"][];
            /**
             * Length
             * @enum {string}
             */
            length: "short" | "standard" | "detailed";
            /** Notes */
            notes: string[];
        };
        /** TimelineEntry */
        TimelineEntry: {
            /** Text */
            text: string;
            fact_kind: components["schemas"]["FactKind"] | null;
            /**
             * Learned On
             * Format: date
             */
            learned_on: string;
            citation: components["schemas"]["Citation"];
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    list_meetings_api_meetings_get: {
        parameters: {
            query?: {
                status?: ("upcoming" | "done") | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MeetingSummary"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    submit_notes_api_meetings__meeting_id__notes_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                meeting_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NotesRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobAccepted"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_job_api_jobs__job_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobStatus"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    read_brief_api_meetings__meeting_id__brief_get: {
        parameters: {
            query?: {
                mode?: "memory" | "no_memory";
            };
            header?: never;
            path: {
                meeting_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Brief"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_brief_api_meetings__meeting_id__brief_post: {
        parameters: {
            query?: {
                mode?: "memory" | "no_memory";
            };
            header?: never;
            path: {
                meeting_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Brief"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    post_feedback_api_briefs__brief_id__feedback_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                brief_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FeedbackRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StyleProfile"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_style_api_style_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StyleProfile"];
                };
            };
        };
    };
    contact_timeline_api_contacts__contact_id__timeline_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                contact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContactTimeline"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    health_api_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
}
