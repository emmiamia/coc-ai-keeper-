"""Bounded investigation loop; scenario data, never an LLM, authorizes state."""
import json
import re
from uuid import uuid4
from app.models.game import Session, PendingPush
from app.agent.models import KeeperDecision, NarrationChoice, TurnResult
from app.agent.mcp_client import SkillResult
from app.agent.turn_store import TurnStore, TurnConflict
from app.llm.provider import LLMRequest

class RejectedDecision(ValueError):
    pass

class KeeperOrchestrator:
    def __init__(self, states, scenarios, rules, mechanics, provider):
        self.states,self.scenarios,self.rules = states,scenarios,rules
        self.mechanics,self.provider = mechanics,provider
        self.turns = TurnStore(states)

    def _fallback(self, session_id, turn_id, status, message):
        return TurnResult(status=status,session=self.states.get(session_id),narration=message,turn_id=turn_id)

    def _context(self, session):
        state = session.state
        context = self.scenarios.get_context(session.scenario_id,state)
        # Only rules required by checks actually present in this scoped context.
        npc_checks = [check for npc in context.npcs for item in npc.knowledge_items for check in item.check_alternatives]
        rule_ids = sorted({'skill_'+check.difficulty for clue in context.available_clues for check in [*clue.required_checks,*clue.alternative_checks]})
        rule_ids = sorted(set(rule_ids) | {'skill_'+check.difficulty for check in npc_checks})
        rules = [self.rules.get_rule(i).model_dump() for i in rule_ids]
        if any(c.push_allowed for c in npc_checks) or any(check.push_allowed for clue in context.available_clues for check in [*clue.required_checks,*clue.alternative_checks]):
            rules.append(self.rules.get_rule('pushed_roll').model_dump())
        blocked = []
        if context.location:
            for clue_id in context.location.clue_ids:
                clue = self.scenarios.get_clue(session.scenario_id, clue_id)
                missing = set(clue.availability.discovered_clues) - set(state.discovered_clues)
                if missing:
                    blocked.append(dict(clue_id=clue.id, action_categories=clue.discovery_actions,
                                        missing_questions=self._missing_questions(session, clue)))
        return context, dict(state=state.model_dump(),scenario_context=context.model_dump(), blocked_investigations=blocked,
                            rules=rules,check_guidance=self.rules.get_check_guidance().model_dump())

    def _validate_ids(self, session, context, decision):
        sid = session.scenario_id
        if decision.clue_id:
            self.scenarios.get_clue(sid,decision.clue_id)
            if not context.location or decision.clue_id not in context.location.clue_ids:
                raise RejectedDecision('Clue is outside scoped location')
        for npc_id in decision.npc_ids:
            self.scenarios.get_npc(sid,npc_id)
            if npc_id not in {n.id for n in context.npcs}: raise RejectedDecision('Unscoped NPC')
        selected_items = {item.id for npc in context.npcs if npc.id in decision.npc_ids for item in npc.knowledge_items}
        if any(i not in selected_items for i in decision.knowledge_item_ids):
            raise RejectedDecision('Unknown or unscoped NPC knowledge')
        for event_id in decision.event_ids:
            self.scenarios.get_event(sid,event_id)
            if not context.location or event_id not in context.location.event_ids: raise RejectedDecision('Unscoped event')
        for encounter_id in decision.encounter_ids:
            self.scenarios.get_encounter(sid,encounter_id)
            if not context.location or encounter_id not in context.location.encounter_ids: raise RejectedDecision('Unscoped encounter')
        for clue_id in decision.depends_on_clue_ids:
            self.scenarios.get_clue(sid,clue_id)

    def _missing_questions(self, session, clue):
        questions = []
        for prerequisite_id in clue.availability.discovered_clues:
            if prerequisite_id not in session.state.discovered_clues:
                prerequisite = self.scenarios.get_clue(session.scenario_id, prerequisite_id)
                if prerequisite.discovery_question:
                    questions.append(prerequisite.discovery_question)
        return list(dict.fromkeys(questions))

    def _clarification_text(self, session, decision):
        # Only repository-authored visibility labels may explain a missing fact.
        # Never copy player_reveal, keeper_truth, model guidance or internal flags.
        if decision.clue_id:
            clue = self.scenarios.get_clue(session.scenario_id, decision.clue_id)
            questions = self._missing_questions(session, clue)
            if questions:
                return 'You have not established ' + '; '.join(questions) + ' yet. What would you like to investigate next?'
            if not clue.availability.matches(session.state, decision.action_category):
                return 'You do not yet have the information or access needed to investigate that target. What would you like to investigate here?'
            if session.state.pending_push:
                return 'That attempt is already resolved. A pushed attempt needs an explicit choice and a changed approach; it cannot be repeated automatically.'
        if decision.action_type == 'move':
            return 'Please choose a destination you already know and can currently reach.'
        if decision.action_type == 'talk':
            return 'Who would you like to speak with here, and what would you like to ask?'
        return 'You do not yet have enough information to identify that target or resolve that action. Please describe what you want to investigate or ask about.'

    def _remember_unlocks(self, sid, state, clue):
        # Authored route permission alone does not bypass its discovery gate.
        for location_id in clue.unlocks.locations:
            location = self.scenarios.get_location(sid, location_id)
            if location.access_conditions.matches(state) and location_id not in state.known_locations:
                state.known_locations.append(location_id)

    def _apply_authorized_changes(self, sid, state, clue, outcome):
        changes = outcome.state_changes
        # Clue outcomes cannot execute arbitrary cross-entity disclosures,
        # movement, phase/time changes or chained events.
        if changes.reveal_information or changes.current_location or changes.phase:
            raise RejectedDecision('Outcome transition is outside this slice')
        if any(i != clue.id for i in changes.discover_clues):
            raise RejectedDecision('Cross-clue discovery is outside this slice')
        for i in changes.discover_clues:
            self.scenarios.get_clue(sid,i)
            if i not in state.discovered_clues: state.discovered_clues.append(i)
        state.story_flags.update(changes.flags)
        if clue.id in state.discovered_clues:
            self._remember_unlocks(sid, state, clue)

    def _payload(self, state, snippets, result=None):
        return 'completed', dict(state=state.model_dump(), mechanics=result.model_dump() if result else None,
                                 snippets=snippets, required=list(range(len(snippets))))

    def _check_option(self, state, checks, decision):
        # The model may choose among authored alternatives, never invent one.
        preferred = [c for c in checks if c.skill_name == decision.requested_skill]
        if decision.social_approach != 'ordinary':
            preferred = [c for c in checks if c.skill_name.lower().replace(' ', '_') == decision.social_approach]
            if not preferred:
                return None
        return next((c for c in (preferred or checks) if c.skill_name in state.skills), None)

    async def _roll(self, state, check):
        if self.rules.get_rule('skill_'+check.difficulty).mcp_tool != 'skill_check':
            raise RejectedDecision('Unsupported rule mapping')
        value = state.skills[check.skill_name]
        raw = await self.mechanics.skill_check(check.skill_name, value, check.difficulty)
        result = SkillResult.model_validate(raw.model_dump() if isinstance(raw, SkillResult) else raw)
        if (result.skill, result.skill_value, result.difficulty) != (check.skill_name, value, check.difficulty):
            raise RejectedDecision('Tool response does not match authorized check')
        return result

    def _npc_changes(self, sid, state, npc, item, changes):
        if changes.current_location or changes.phase:
            raise RejectedDecision('Unplanned NPC transition')
        allowed_items = {i.id for i in npc.knowledge_items if i.access != 'keeper_only'}
        if any(i not in allowed_items or i != item.id for i in changes.reveal_information):
            raise RejectedDecision('Cross-information disclosure')
        for clue_id in changes.discover_clues:
            clue = self.scenarios.get_clue(sid, clue_id)
            if clue.location_id != state.current_location or not clue.availability.matches(state, 'talk'):
                raise RejectedDecision('Unauthorized NPC clue')
            if clue_id not in state.discovered_clues:
                state.discovered_clues.append(clue_id)
        state.story_flags.update(changes.flags)
        for i in changes.reveal_information:
            if i not in state.revealed_information:
                state.revealed_information.append(i)

    async def _talk(self, session, context, decision, turn_id):
        if len(decision.npc_ids) != 1 or decision.clue_id:
            return 'clarification', None
        npc = next(n for n in context.npcs if n.id == decision.npc_ids[0])
        state = session.state.model_copy(deep=True)
        items = {i.id: i for i in npc.knowledge_items}
        if any(i not in items for i in decision.knowledge_item_ids):
            raise RejectedDecision('Unknown NPC knowledge')
        if not decision.question_answerable:
            return self._payload(state, [f'{npc.player_name} has no confirmed information to answer that question.'])
        selected = [items[i] for i in decision.knowledge_item_ids] if decision.knowledge_item_ids else [
            i for i in items.values() if i.access in ('public', 'conversational')]
        safe, gated = [], []
        for item in selected:
            if item.access == 'keeper_only':
                continue
            if item.reveal_conditions.matches(state, 'talk') and (item.access != 'guarded' or item.id in state.revealed_information or item.reveal_conditions != type(item.reveal_conditions)()):
                safe.append(item)
                continue
            if item.access == 'guarded' and decision.social_approach == 'ordinary':
                continue
            shadow = state.model_copy(deep=True)
            # Check grants are explicit authored flags, not arbitrary mutations.
            if item.check_grants.discover_clues or item.check_grants.reveal_information or item.check_grants.current_location or item.check_grants.phase:
                raise RejectedDecision('Invalid social check grant')
            shadow.story_flags.update(item.check_grants.flags)
            if (item.check_alternatives and decision.social_approach in item.check_approaches
                    and item.reveal_conditions.matches(shadow, 'talk')):
                gated.append(item)
        if len(gated) > 1:
            return 'clarification', None
        # Preflight every possible authored disclosure before executing a check.
        for item in safe:
            self._npc_changes(session.scenario_id, state.model_copy(deep=True), npc, item, item.state_changes)
        result = None
        snippets = []
        if gated:
            item = gated[0]
            check = self._check_option(state, item.check_alternatives, decision)
            if check is None or (state.pending_push and state.pending_push.context == 'talk:'+item.id):
                return 'clarification', None
            shadow = state.model_copy(deep=True)
            shadow.story_flags.update(item.check_grants.flags)
            self._npc_changes(session.scenario_id, shadow, npc, item, item.state_changes)
            result = await self._roll(state, check)
            if result.outcome == 'success':
                state.story_flags.update(item.check_grants.flags)
                safe.append(item)
            else:
                snippets.append(f'{npc.player_name} remains unwilling to share more. Your {check.skill_name} check was unsuccessful.')
                if check.push_allowed and state.pending_push is None:
                    state.pending_push = PendingPush(check_id=turn_id, skill_name=check.skill_name,
                        skill_value=state.skills[check.skill_name], difficulty=check.difficulty, context='talk:'+item.id,
                        allowed=True, consequence_reference=check.push_consequence_reference or 'Resolve the authored consequence before pushing')
                    snippets.append('You may propose a changed approach for a pushed attempt; it will not happen automatically.')
        for item in safe:
            self._npc_changes(session.scenario_id, state, npc, item, item.state_changes)
            if item.id not in state.revealed_information:
                state.revealed_information.append(item.id)
            snippets.append(f'{npc.player_name} tells you: {item.information}')
        return self._payload(state, snippets or [f'{npc.player_name} offers no further information on that subject.'], result)

    async def _resolve(self, session, context, decision, message, turn_id):
        self._validate_ids(session,context,decision)
        if set(decision.depends_on_clue_ids) - set(session.state.discovered_clues):
            return 'clarification', None
        if decision.status == 'unsupported' or decision.action_type == 'unsupported' or decision.mechanic in ('combat','roll_dice','san_check'):
            return 'unsupported',None
        if decision.status == 'clarification' or decision.action_type == 'clarification_needed':
            return 'clarification', None
        if decision.event_ids or decision.encounter_ids:
            return 'unsupported', None
        if decision.action_type == 'hypothesize':
            return self._payload(session.state.model_copy(deep=True), ['You can keep that possibility in mind, but a theory alone does not establish what happened.'])
        if decision.action_type == 'move':
            if not decision.destination_id or decision.npc_ids or decision.clue_id:
                return 'clarification', None
            if decision.destination_id not in self.scenarios.known_location_ids(session.scenario_id, session.state):
                return 'clarification', None
            state = session.state.model_copy(deep=True)
            location = self.scenarios.player_location(session.scenario_id, decision.destination_id)
            state.current_location = location.id
            for collection in (state.known_locations, state.visited_locations):
                if location.id not in collection: collection.append(location.id)
            return self._payload(state, [f'You arrive at {location.name}.', location.description])
        if decision.action_type == 'talk':
            return await self._talk(session, context, decision, turn_id)
        if decision.npc_ids:
            return 'unsupported', None
        if decision.action_type == 'observe':
            return self._payload(session.state.model_copy(deep=True), [self.scenarios.player_location(session.scenario_id, session.state.current_location).description])
        state = session.state.model_copy(deep=True)
        public_location = self.scenarios.player_location(session.scenario_id,state.current_location)
        snippets = [public_location.description]
        required = [0]
        result = None
        if decision.clue_id is None:
            if decision.check_required or decision.mechanic != 'none' or decision.proposes_transition:
                return 'unsupported',None
            if decision.action_category not in ('observe','look_around'):
                return 'clarification',None
        else:
            if state.pending_push is not None and state.pending_push.context in (*self.scenarios.get_clue(session.scenario_id, decision.clue_id).discovery_actions, 'investigate:'+decision.clue_id):
                return 'clarification',None
            clue = self.scenarios.get_clue(session.scenario_id,decision.clue_id)
            if decision.action_type in ('investigate','mechanical_action') and re.match(
                    r"^(?:maybe\b|could\s+(?!i\b|we\b)|is\b|are\b|i\s+(?:think\b|believe\b|suspect\b|wonder\b|do\s+not\b|don't\b))", message.strip(), re.I):
                return self._payload(state, ['You can keep that possibility in mind, but a theory alone does not establish what happened.'])
            if decision.action_category not in clue.discovery_actions:
                return 'clarification',None
            # Narrow explicit-action guard: guesses/questions/negated requests
            # cannot become searches merely because the classifier selected one.
            verb = decision.action_category.split('_')[0]
            if decision.action_type not in ('investigate','mechanical_action') and not re.match(r'^(?:i\s+)?(?:(?:carefully|thoroughly|quietly)\s+)?'+re.escape(verb)+r'\b',message.strip(),re.I):
                return 'clarification',None
            if not clue.availability.matches(state,decision.action_category):
                return 'clarification',None
            if clue.id in state.discovered_clues:
                snippets.append(self.scenarios.player_clue(session.scenario_id,clue.id,state).reveal)
                required.append(len(snippets)-1)
            else:
                if len(clue.required_checks) > 1:
                    # Multiple mandatory checks need a dedicated plan; never infer
                    # a sequence of irreversible rolls from model prose.
                    return 'unsupported',None
                checks = clue.required_checks or clue.alternative_checks
                if not checks:
                    for authored in (clue.success, type(clue.success)(state_changes=clue.state_changes)):
                        self._apply_authorized_changes(session.scenario_id, state, clue, authored)
                    if clue.id not in state.discovered_clues: state.discovered_clues.append(clue.id)
                    self._remember_unlocks(session.scenario_id, state, clue)
                    snippets.append(self.scenarios.player_clue(session.scenario_id, clue.id, state).reveal)
                    return self._payload(state, snippets)
                check = self._check_option(state, checks, decision)
                if check is None: return 'clarification', None
                if decision.mechanic not in ('none','skill_check'):
                    return 'unsupported',None
                rule = self.rules.get_rule('skill_'+check.difficulty)
                if rule.mcp_tool != 'skill_check': raise RejectedDecision('Unsupported rule mapping')
                value = state.skills.get(check.skill_name)
                if value is None: return 'clarification',None
                # Validate authored transitions before any irreversible roll.
                if clue.failure.state_changes.discover_clues:
                    return 'unsupported',None
                for authored in (clue.success,clue.failure,type(clue.success)(state_changes=clue.state_changes)):
                    self._apply_authorized_changes(session.scenario_id,state.model_copy(deep=True),clue,authored)
                # The scenario's skill/difficulty override every model suggestion.
                raw = await self.mechanics.skill_check(check.skill_name,value,check.difficulty)
                result = SkillResult.model_validate(raw.model_dump() if isinstance(raw,SkillResult) else raw)
                if (result.skill,result.skill_value,result.difficulty) != (check.skill_name,value,check.difficulty):
                    raise RejectedDecision('Tool response does not match authorized check')
                outcome = clue.success if result.outcome == 'success' else clue.failure
                self._apply_authorized_changes(session.scenario_id,state,clue,outcome)
                if result.outcome == 'success':
                    # Successful resolution authorizes selected clue discovery;
                    # failed outcomes never get this implicit authorization.
                    if clue.id not in state.discovered_clues: state.discovered_clues.append(clue.id)
                    self._apply_authorized_changes(session.scenario_id,state,clue,
                        type(outcome)(state_changes=clue.state_changes))
                    snippets.append(self.scenarios.player_clue(session.scenario_id,clue.id,state).reveal)
                else:
                    snippets.append(f'You examine what is available, but nothing new stands out. Your {check.skill_name} check was unsuccessful.')
                    if check.push_allowed and state.pending_push is None:
                        self.rules.get_rule('pushed_roll')
                        state.pending_push = PendingPush(check_id=turn_id,skill_name=check.skill_name,
                            skill_value=value,difficulty=check.difficulty,context='investigate:'+clue.id if decision.action_type else decision.action_category,
                            allowed=True,consequence_reference=check.push_consequence_reference or 'Scenario consequence must be resolved before pushing')
                        snippets.append('A pushed attempt may be possible, but it requires your explicit choice and a changed approach.')
                required.extend(range(1,len(snippets)))
        return 'completed',dict(state=state.model_dump(),mechanics=result.model_dump() if result else None,
                                snippets=snippets,required=required)

    async def _narrate(self, payload):
        # No raw player text, decision guidance, hidden context, flags or history.
        # LLM may select/order approved text only; free prose is never rendered.
        try:
            response = await self.provider.generate(LLMRequest(
                system_instruction='Select a coherent order of the approved sentence IDs. Include all required IDs. Do not return prose or new facts.',
                user_message=json.dumps({'approved_sentences':payload['snippets'],'required_ids':payload['required']}),
                response_schema=NarrationChoice))
            choice = NarrationChoice.model_validate(response.structured_data)
            if not choice.sentence_ids or len(set(choice.sentence_ids)) != len(choice.sentence_ids):
                raise RejectedDecision('Invalid narration selection')
            if any(i < 0 or i >= len(payload['snippets']) for i in choice.sentence_ids):
                raise RejectedDecision('Invalid narration reference')
            if not set(payload['required']) <= set(choice.sentence_ids):
                raise RejectedDecision('Missing required narration')
            return ' '.join(payload['snippets'][i] for i in choice.sentence_ids)
        except Exception:
            # Failed narration never rerolls or invalidates a trusted resolution.
            return ' '.join(payload['snippets'])

    async def act(self, session_id, message, turn_id=None):
        turn_id = turn_id or str(uuid4())
        if not message.strip():
            return self._fallback(session_id,turn_id,'clarification','Please describe your action.')
        owns_pending = False
        try:
            record = self.turns.begin(session_id,turn_id,message)
            owns_pending = record['status'] == 'new'
            if record['status'] == 'completed':
                saved = Session.model_validate_json(record['completed_session'])
                return TurnResult(status=(record['payload'] or {}).get('outcome','completed'),session=saved,narration=saved.messages[-1].content,turn_id=turn_id)
            if record['status'] in ('pending','failed'):
                return self._fallback(session_id,turn_id,'error','This turn cannot be rerolled automatically; it needs review.')
            if record['status'] == 'resolved':
                payload = record['payload']
            else:
                session = Session.model_validate_json(record['baseline'])
                context, internal = self._context(session)
                response = await self.provider.generate(LLMRequest(
                    system_instruction='Interpret the player action using the scoped scenario and rules. Do not mutate state or generate dice. Scenario checks take priority. Guessed information is not discovered. Classify action_type as observe, hypothesize, talk, move, investigate, mechanical_action, unsupported or clarification_needed. Ordinary observation uses only the public location description, no check. Theories do not confirm hidden facts. Talk selects exactly one accessible npc_id and only relevant knowledge_item_ids; set question_answerable false for questions outside its knowledge. Default talk selects ordinary knowledge. Use social_approach only when the player actually proposes it. Move selects destination_id only from known_destinations. When an investigation is blocked by missing discovery, select its clue_id from blocked_investigations and classify clarification_needed, without accepting the hidden premise. Investigate matches an authored clue and its discovery action category by meaning, including paraphrases; never classify a theory as a search. Authored required_checks and alternative_checks govern mechanics. Do not select event_ids or encounter_ids for ordinary actions. Full combat and unplanned events remain unsupported.',
                    user_message=json.dumps({'internal_context':internal,'player_action':message, 'known_destinations':[{'id':i,'name':self.scenarios.player_location(session.scenario_id,i).name} for i in self.scenarios.known_location_ids(session.scenario_id,session.state)]}),response_schema=KeeperDecision))
                decision = KeeperDecision.model_validate(response.structured_data)
                status,payload = await self._resolve(session,context,decision,message,turn_id)
                if status == 'clarification':
                    text = self._clarification_text(session, decision)
                    payload = dict(state=session.state.model_dump(), mechanics=None,
                                   outcome='clarification', narration=text)
                elif status != 'completed':
                    self.turns.fail(turn_id)
                    return self._fallback(session_id,turn_id,status,
                        'That action requires mechanics beyond this investigation loop; no mechanics were invented.')
                self.turns.record_resolution(turn_id,payload)
            # Clarification is already safe authored text; it needs no second LLM.
            narration = payload['narration'] if payload.get('outcome') == 'clarification' else await self._narrate(payload)
            saved = self.turns.complete(turn_id,narration)
            return TurnResult(status=payload.get('outcome','completed'),session=saved,narration=narration,turn_id=turn_id)
        except Exception:
            if owns_pending: self.turns.fail(turn_id)
            return self._fallback(session_id,turn_id,'error','The turn could not be completed safely. The previous valid state is preserved.')
