"""Population studies, social simulation, and their graph views (contract v3, contracts/README.md §14).

Handler bodies are owned by the backend agent; signatures are the contract.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas.common import CountryCode
from app.schemas.population import (
    CampaignComparison,
    FollowUpAnswer,
    FollowUpCreate,
    FollowUpPage,
    GraphView,
    GroupQuestionCreate,
    GroupQuestionPage,
    GroupQuestionResult,
    InterviewPage,
    ParticipantDetail,
    ParticipantPage,
    Population,
    PopulationPage,
    PopulationStudyCreate,
    PopulationStudyPage,
    PopulationStudyResult,
    ReactionCategory,
    SocialPostPage,
    SocialSimulationCreate,
    SocialSimulationPage,
    SocialSimulationResult,
)
from app.schemas.runs import RunAccepted
from app.services import population

router = APIRouter(tags=["population-studies"])
GraphLimit = Annotated[int, Query(ge=10, le=300, description="Maximum nodes; truncated=true when exceeded.")]


# --- Population studies ---------------------------------------------------------------------------------------


@router.post(
    "/studies/{study_id}/population-studies", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted
)
async def start_population_study(study_id: UUID, body: PopulationStudyCreate, user: CurrentUser) -> RunAccepted:
    """Construct or reuse a population and interview it about one campaign version (run_type population_study)."""
    return await population.start_population_study(user.id, study_id, body)


@router.get("/studies/{study_id}/population-studies", response_model=PopulationStudyPage)
async def list_population_studies(
    study_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0
) -> PopulationStudyPage:
    return await population.list_population_studies(user.id, study_id, limit, offset)


@router.get("/population-studies/{population_study_id}", response_model=PopulationStudyResult)
async def get_population_study(population_study_id: UUID, user: CurrentUser) -> PopulationStudyResult:
    return await population.get_population_study(user.id, population_study_id)


@router.get("/population-studies/{population_study_id}/interviews", response_model=InterviewPage)
async def list_interviews(
    population_study_id: UUID,
    user: CurrentUser,
    group_id: str | None = None,
    region: CountryCode | None = None,
    reaction: ReactionCategory | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> InterviewPage:
    return await population.list_interviews(user.id, population_study_id, group_id, region, reaction, limit, offset)


# --- Participant memory and interrogation (README §14.9) ------------------------------------------------------


@router.get("/population-studies/{population_study_id}/participants/{participant_id}", response_model=ParticipantDetail)
async def get_participant(population_study_id: UUID, participant_id: UUID, user: CurrentUser) -> ParticipantDetail:
    """Profile, current stance, and memories (interview, seen and own posts, earlier answers) in this study."""
    return await population.participant_detail(user.id, population_study_id, participant_id)


@router.post(
    "/population-studies/{population_study_id}/participants/{participant_id}/questions",
    status_code=status.HTTP_201_CREATED,
    response_model=FollowUpAnswer,
)
async def ask_participant(
    population_study_id: UUID, participant_id: UUID, body: FollowUpCreate, user: CurrentUser
) -> FollowUpAnswer:
    """One bounded model call: the participant answers in character from its profile and memories."""
    return await population.ask_participant(user.id, population_study_id, participant_id, body)


@router.get("/population-studies/{population_study_id}/participants/{participant_id}/questions", response_model=FollowUpPage)
async def list_participant_questions(
    population_study_id: UUID, participant_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0
) -> FollowUpPage:
    return await population.list_participant_questions(user.id, population_study_id, participant_id, limit, offset)


@router.post(
    "/population-studies/{population_study_id}/groups/{group_id}/questions",
    status_code=status.HTTP_201_CREATED,
    response_model=GroupQuestionResult,
)
async def ask_group(
    population_study_id: UUID, group_id: str, body: GroupQuestionCreate, user: CurrentUser
) -> GroupQuestionResult:
    """A seeded sample of the group answers in one batched call; the tally covers the sample only."""
    return await population.ask_group(user.id, population_study_id, group_id, body)


@router.get("/population-studies/{population_study_id}/groups/{group_id}/questions", response_model=GroupQuestionPage)
async def list_group_questions(
    population_study_id: UUID, group_id: str, user: CurrentUser, limit: Limit = 20, offset: Offset = 0
) -> GroupQuestionPage:
    return await population.list_group_questions(user.id, population_study_id, group_id, limit, offset)


# --- Populations ----------------------------------------------------------------------------------------------


@router.get("/projects/{project_id}/populations", response_model=PopulationPage)
async def list_populations(project_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0) -> PopulationPage:
    return await population.list_populations(user.id, project_id, limit, offset)


@router.get("/populations/{population_id}", response_model=Population)
async def get_population(population_id: UUID, user: CurrentUser) -> Population:
    return await population.get_population(user.id, population_id)


@router.get("/populations/{population_id}/participants", response_model=ParticipantPage)
async def list_participants(
    population_id: UUID,
    user: CurrentUser,
    group_id: str | None = None,
    region: CountryCode | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> ParticipantPage:
    return await population.list_participants(user.id, population_id, group_id, region, limit, offset)


# --- Social simulation ----------------------------------------------------------------------------------------


@router.post("/social-simulations", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted)
async def start_social_simulation(body: SocialSimulationCreate, user: CurrentUser) -> RunAccepted:
    """Bounded multi-round peer exposure on a completed population study (run_type social_simulation)."""
    return await population.start_social_simulation(user.id, body)


@router.get("/population-studies/{population_study_id}/social-simulations", response_model=SocialSimulationPage)
async def list_social_simulations(
    population_study_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0
) -> SocialSimulationPage:
    return await population.list_social_simulations(user.id, population_study_id, limit, offset)


@router.get("/social-simulations/{simulation_id}", response_model=SocialSimulationResult)
async def get_social_simulation(simulation_id: UUID, user: CurrentUser) -> SocialSimulationResult:
    return await population.get_social_simulation(user.id, simulation_id)


@router.get("/social-simulations/{simulation_id}/posts", response_model=SocialPostPage)
async def list_social_posts(
    simulation_id: UUID,
    user: CurrentUser,
    round_index: Annotated[int | None, Query(ge=1, le=5)] = None,
    group_id: str | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> SocialPostPage:
    return await population.list_social_posts(user.id, simulation_id, round_index, group_id, limit, offset)


# --- Graph views ----------------------------------------------------------------------------------------------


@router.get("/populations/{population_id}/landscape", response_model=GraphView)
async def get_audience_landscape(
    population_id: UUID,
    user: CurrentUser,
    region: CountryCode | None = None,
    interest: str | None = None,
    limit: GraphLimit = 120,
) -> GraphView:
    """Graph B: audience groups linked by a documented interest-profile similarity and by shared evidence."""
    return await population.landscape(user.id, population_id, region, interest, limit)


@router.get("/population-studies/{population_study_id}/reaction-map", response_model=GraphView)
async def get_reaction_map(
    population_study_id: UUID,
    user: CurrentUser,
    element: str | None = None,
    group_id: str | None = None,
    limit: GraphLimit = 120,
) -> GraphView:
    """Graph C: campaign elements, groups, themes, reactions, evidence, and recommendations from stored interviews."""
    return await population.reaction_map(user.id, population_study_id, element, group_id, limit)


@router.get("/campaigns/{campaign_id}/population-comparison", response_model=CampaignComparison)
async def get_campaign_comparison(
    campaign_id: UUID,
    user: CurrentUser,
    population_id: UUID,
    population_study_ids: Annotated[list[UUID], Query(min_length=2, max_length=4)],
) -> CampaignComparison:
    """Graph D: campaign versions compared on the same population and interview protocol."""
    return await population.comparison(user.id, campaign_id, population_id, population_study_ids)


@router.get("/social-simulations/{simulation_id}/diffusion", response_model=GraphView)
async def get_social_diffusion(
    simulation_id: UUID,
    user: CurrentUser,
    round_index: Annotated[int | None, Query(ge=1, le=5)] = None,
    limit: GraphLimit = 150,
) -> GraphView:
    """Who influenced whom: group-level flows plus a bounded participant/post subgraph."""
    return await population.diffusion(user.id, simulation_id, round_index, limit)
