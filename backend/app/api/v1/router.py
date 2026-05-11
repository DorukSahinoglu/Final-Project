from fastapi import APIRouter

from app.api.v1.routes import geocode, health, jobs, matrix, projects, solutions, solve


api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(geocode.router, tags=["geocode"])
api_router.include_router(matrix.router, prefix="/matrix", tags=["matrix"])
api_router.include_router(solve.router, prefix="/solve", tags=["solve"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(solutions.router, prefix="/solutions", tags=["solutions"])
