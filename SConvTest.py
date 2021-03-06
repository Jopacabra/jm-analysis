import os
import numpy as np
import pandas as pd
import logging
import hic
import plasma
import jets
import plasma_interaction as pi
import config
import utilities
from utilities import resultsFrame, tempDir


# Exits temporary directory, saves dataframe to pickle, and dumps all temporary data.
def safe_exit(resultsDataFrame, temp_dir, filename, identifier):
    # Save dataframe
    # Note that we exit the directory first in order to retain a valid current working directory when cleaned up.
    # This prevents os.get_cwd() from throwing an error.
    os.chdir('..')

    # Save the dataframe into the identified results folder
    logging.info('Saving progress...')
    logging.debug(resultsDataFrame)
    resultsDataFrame.to_pickle(os.getcwd() + '/{}.pkl'.format(filename))  # Save dataframe to pickle

    # Return to the project root.
    os.chdir('..')
    os.chdir('..')

    # Clear everything in the temporary directory and delete it, thereby deleting all event files.
    logging.info('Cleaning temporary directory...')
    logging.debug('This dumps all of the event data!')
    try:
        temp_dir.cleanup()
    except TypeError:
        pass


# Function to generate a new HIC event and sample config.NUM_SAMPLES jets in it.
def run_event(eventNo, grid_step=config.transport.GRID_STEP, time_step=config.transport.TIME_STEP, seed=None):

    # Generate empty results frame
    results = resultsFrame()

    ###############################
    # Generate new event geometry #
    ###############################

    # Run event generation using config setttings
    trentoDataframe = hic.generate_event(grid_step=grid_step, time_step=time_step, seed=seed)

    # Record seed selected
    seed = trentoDataframe.iloc[0]['seed']

    # Open the hydro file and create file object for manipulation.
    plasmaFilePath = 'viscous_14_moments_evo.dat'
    current_file = plasma.osu_hydro_file(file_path=plasmaFilePath, event_name='seed: {}'.format(seed))

    # Create event object
    # This asks the hydro file object to interpolate the relevant functions and pass them on to the plasma object.
    current_event = plasma.plasma_event(event=current_file)

    ################
    # Jet Analysis #
    ################
    # Oversample the background with jets
    for jetNo in range(0, 500):

        ##################
        # Create new jet #
        ##################
        # Select jet production point
        if not config.mode.VARY_POINT:
            x0 = 0
            y0 = 0
        else:
            newPoint = hic.generate_jet_point(current_event)
            x0, y0 = newPoint[0], newPoint[1]

        # Select jet production angle
        theta0 = np.random.uniform(0, 2 * np.pi)

        # Generate jet object
        current_jet = jets.jet(x0=x0, y0=y0,
                               theta0=theta0, event=current_event, energy=config.jet.JET_ENERGY)

        # Sample for shower correction
        # Currently just zero
        current_jet.shower_sample()

        ################################################
        # Find phase change times along jet trajectory #
        ################################################
        logging.info('Calculating phase change times...')

        # Initialize transition time flags
        t_hrg = False
        t_unhydro = False

        # Initialize counters for total time spent in each phase
        plasma_time_total = 0
        hrg_time_total = 0
        unhydro_time_total = 0

        # Iterate over jet trajectory and find phase transition times and time spent in each phase
        # Note that we work with the precision of the timestep. While this isn't strictly necessary,
        # this is the maximum time precision that can be physically meaningful.
        for t in np.arange(start=current_event.t0, stop=current_event.tf, step=config.transport.TIME_STEP):

            # If the jet is still in the event geometry, check the temperature at its position.
            # If it isn't, this position would make an out-of-bounds call to the interpolation function
            if pi.pos_cut(event=current_event, jet=current_jet, time=t) and pi.time_cut(event=current_event, time=t):
                current_temp = current_jet.temp(current_event, time=t)
            else:
                # Quit the loop - jet can't re-enter the geometry.
                break

            # Add to the total jet travel time
            if current_temp > config.transport.hydro.T_HRG:
                plasma_time_total += config.transport.TIME_STEP

            # Check if temp is under hadronization temp
            if current_temp < config.transport.hydro.T_HRG:
                # Check if this is the first transition below hadron gas temp
                if bool(t_hrg) is False:
                    # Record time as transition time for hadron gas
                    t_hrg = t

                # Check if above the unhydrodynamic temperature
                if current_temp > config.transport.hydro.T_UNHYDRO:
                    # Record one additional timestep spent in the hadron gas
                    hrg_time_total += config.transport.TIME_STEP

            # Check if temp is under unhydrodynamic temp
            if current_temp < config.transport.hydro.T_UNHYDRO:
                # Check if this is the first transition below unhydrodynamic temp
                if bool(t_unhydro) is False:
                    t_unhydro = t

                # Record one additional timestep spent in unhydrodynamic data
                unhydro_time_total += config.transport.TIME_STEP

        # Calculate momentPlasma
        logging.info('Calculating unhydrodynamic moment:')
        momentUnhydro, momentUnhydroErr = pi.moment_integral(event=current_event, jet=current_jet, k=config.moment.K,
                                                             minTemp=0, maxTemp=config.transport.hydro.T_UNHYDRO)
        logging.info('Calculating hadron gas moment:')
        momentHrg, momentHrgErr = pi.moment_integral(event=current_event, jet=current_jet, k=config.moment.K,
                                                     minTemp=config.transport.hydro.T_UNHYDRO,
                                                     maxTemp=config.transport.hydro.T_HRG)
        logging.info('Calculating plasma moment:')
        momentPlasma, momentPlasmaErr = pi.moment_integral(event=current_event, jet=current_jet, k=config.moment.K,
                                                           minTemp=config.transport.hydro.T_HRG)

        # Calculate deflection angle
        # Basic trig with k=0.
        if config.moment.K == 0:
            deflection_angle_plasma = np.arctan((momentPlasma / current_jet.energy)) * (180 / np.pi)
            deflection_angle_plasma_error = np.arctan((momentPlasmaErr / current_jet.energy)) * (180 / np.pi)
            deflection_angle_hrg = np.arctan((momentHrg / current_jet.energy)) * (180 / np.pi)
            deflection_angle_hrg_error = np.arctan((momentHrgErr / current_jet.energy)) * (180 / np.pi)
            deflection_angle_unhydro = np.arctan((momentUnhydro / current_jet.energy)) * (180 / np.pi)
            deflection_angle_unhydro_error = np.arctan((momentUnhydroErr / current_jet.energy)) * (180 / np.pi)
        else:
            deflection_angle_plasma = None
            deflection_angle_plasma_error = None
            deflection_angle_hrg = None
            deflection_angle_hrg_error = None
            deflection_angle_unhydro = None
            deflection_angle_unhydro_error = None

        # Create momentPlasma results dataframe
        momentDataframe = pd.DataFrame(
            {
                "eventNo": [eventNo],
                "jetNo": [jetNo],
                "pT_plasma": [momentPlasma],
                "pT_plasma_err": [momentPlasmaErr],
                "pT_hrg": [momentHrg],
                "pT_hrg_err": [momentHrgErr],
                "pT_unhydro": [momentUnhydro],
                "pT_unhydro_err": [momentUnhydroErr],
                "k_moment": [config.moment.K],
                "def_ang_plasma": [deflection_angle_plasma],
                "def_ang_plasma_err": [deflection_angle_plasma_error],
                "def_ang_hrg": [deflection_angle_hrg],
                "def_ang_hrg_err": [deflection_angle_hrg_error],
                "def_ang_unhydro": [deflection_angle_unhydro],
                "def_ang_unhydro_err": [deflection_angle_unhydro_error],
                "shower_correction": [current_jet.shower_correction],
                "X0": [x0],
                "Y0": [y0],
                "theta0": [theta0],
                "t_unhydro": [t_unhydro],
                "t_hrg": [t_hrg],
                "time_total_plasma": [plasma_time_total],
                "time_total_hrg": [hrg_time_total],
                "time_total_unhydro": [unhydro_time_total],
                "initial_time": [current_event.t0],
                "final_time": [current_event.tf],
                "dx": [grid_step],
                "dt": [time_step],
            }
        )

        # Merge the trento and momentPlasma dataframes
        currentResultDataframe = pd.concat([momentDataframe, trentoDataframe], axis=1)

        results = results.append(currentResultDataframe)

        # Declare jet complete
        logging.info('Jet ' + str(jetNo) + ' Complete')

    return results


################
# Main Program #
################

# Instantiate counters
part = 0
eventNo = 0

# Set up results frame and filename.
temp_dir = None  # Instantiates object for interrupt before temp_dir created.
results = resultsFrame()
identifierString = str(int(np.random.uniform(0, 10000000)))
resultsFilename = 'results' + identifierString + 'p' + str(part)

# Make results directory
if os.path.exists(os.getcwd() + '/results/{}'.format(identifierString)):
    pass
else:
    print('Making results directory...')
    os.mkdir(os.getcwd() + '/results/{}'.format(identifierString))

# Create log file & configure logging to be handled into the file AND stdout
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler(os.getcwd() + '/results/{}/log_{}.log'.format(identifierString, identifierString)),
        logging.StreamHandler()
    ]
)

# Copy config file to results directory, tagged with identifier
utilities.run_cmd(*['cp', 'config.yml', os.getcwd()
                    + '/results/{}/config_{}.yml'.format(identifierString, identifierString)], quiet=True)

# Set timesteps to study:
time_step_array = [0.025, 0.0375, 0.05]

# Run event loop
try:
    for i in range(0,4):
        # Create and move to temporary directory
        temp_dir = tempDir(location=os.getcwd() + '/results/{}'.format(identifierString))

        # Generate a new HIC event and samples config.NUM_SAMPLES jets in it
        # Append returned dataframe to current dataframe
        results = results.append(run_event(eventNo=eventNo, time_step=time_step_array[i], seed=12409235))

        # Exits directory, saves all current data, and dumps temporary files.
        safe_exit(resultsDataFrame=results, temp_dir=temp_dir, filename=resultsFilename, identifier=identifierString)

        if len(results) > 10000:
            part += 1
            resultsFilename = 'results' + identifierString + 'p' + str(part)
            results = resultsFrame()

        eventNo += 1

except KeyboardInterrupt:
    logging.warning('Interrupted!')
    logging.info('Cleaning up...')

    # Clean up and get everything sorted
    safe_exit(resultsDataFrame=results, temp_dir=temp_dir, filename=resultsFilename, identifier=identifierString)

except hic.StopEvent:
    logging.warning('HIC event error.')
    logging.info('Cleaning up...')

    # Clean up and get everything sorted
    safe_exit(resultsDataFrame=results, temp_dir=temp_dir, filename=resultsFilename, identifier=identifierString)

logging.info('Results identifier: {}'.format(identifierString))
logging.info('Please have an excellent day. :)')
