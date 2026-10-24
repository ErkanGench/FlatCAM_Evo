# OR-Tools route solver. Light on purpose: a pool child imports this module, so no camlib, Qt or app here.
import numpy as np

# integer arc costs: distances are multiplied by this before the rounding, so close holes do not get 0
DISTANCE_SCALE = 1000
# search time in seconds if the option is 0
DEFAULT_SEARCH_TIME = 3


def distance_matrix(locs, scale=DISTANCE_SCALE):
    """Euclidean distances of (x, y) tuples times scale, rounded to int; item [i][j] is the cost i -> j."""
    pts = np.asarray(locs, dtype=float).reshape(-1, 2)
    dx = pts[:, 0, None] - pts[None, :, 0]
    dy = pts[:, 1, None] - pts[None, :, 1]
    return np.rint(np.hypot(dx, dy) * scale).astype(np.int64).tolist()


def set_time_limit(search_parameters, opt_time):
    """Time limit in seconds (fractions kept); 0 or None selects DEFAULT_SEARCH_TIME."""
    seconds = float(opt_time) if opt_time else 0.0
    if seconds <= 0:
        seconds = DEFAULT_SEARCH_TIME
    search_parameters.time_limit.FromMilliseconds(int(seconds * 1000))


def solve_route(locations, depot=0, metaheuristic=False, opt_time=0):
    """Returns (route, objective): location indexes in route order and the cost / DISTANCE_SCALE, or (None, None)."""
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    manager = pywrapcp.RoutingIndexManager(len(locations), 1, depot)
    routing = pywrapcp.RoutingModel(manager)
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    if metaheuristic:
        search_parameters.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
    else:
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
    set_time_limit(search_parameters, opt_time)

    # the matrix is evaluated inside OR-Tools, without a Python call for each arc
    transit_index = routing.RegisterTransitMatrix(distance_matrix(locations))
    routing.SetArcCostEvaluatorOfAllVehicles(transit_index)

    assignment = routing.SolveWithParameters(search_parameters)
    if not assignment:
        return None, None

    route = []
    node = routing.Start(0)
    while not routing.IsEnd(node):
        route.append(manager.IndexToNode(node))
        node = assignment.Value(routing.NextVar(node))
    return route, assignment.ObjectiveValue() / DISTANCE_SCALE
