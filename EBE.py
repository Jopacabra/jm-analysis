import os
import math
import tempfile
import logging
import numpy as np
import pandas as pd
import hic
import plasma
import jets
import plasma_interaction as pi
import config
import freestream
import frzout

# Constants & config
resultsFile = 'results' + str(int(np.random.uniform(0, 10000000)))

# the "target" grid max: the grid shall be at least as large as the target
grid_max_target = 15
# next two lines set the number of grid cells and actual grid max,
# which will be >= the target (same algorithm as trento)
grid_n = math.ceil(2*grid_max_target/config.GRID_STEP)
grid_max = .5*grid_n*config.GRID_STEP
logging.info(
    'grid step = %.6f fm, n = %d, max = %.6f fm',
    config.GRID_STEP, grid_n, grid_max
)

# Create and move to temp directory
temp_dir = tempfile.TemporaryDirectory(prefix='JMA_', dir=os.getcwd())
print('Created temp directory {}'.format(temp_dir.name))
os.chdir(temp_dir.name)

# Create results dataframe.
resultsDataframe = resultsDataFrame = pd.DataFrame(
        {
            "eventNo": [],
            "jetNo": [],
            "pT_plasma": [],
            "pT_plasma_error": [],
            "pT_hrg": [],
            "pT_hrg_error": [],
            "pT_unhydro": [],
            "pT_unhydro_error": [],
            "k_moment": [],
            "deflection_angle_plasma": [],
            "deflection_angle_plasma_error": [],
            "deflection_angle_hrg": [],
            "deflection_angle_hrg_error": [],
            "deflection_angle_unhydro": [],
            "deflection_angle_unhydro_error": [],
            "shower_correction": [],
            "X0": [],
            "Y0": [],
            "theta0": [],
            "b": [],
            "npart": [],
            "mult": [],
            "e2": [],
            "e3": [],
            "e4": [],
            "e5": [],
            "seed": [],
            "cmd": [],
        }
    )


# loop N backgrounds
for eventNo in range(0, config.NUM_EVENTS):

    print('Generating new event.')

    ##########
    # Trento #
    ##########

    # Choose random seed
    seed = int(np.random.uniform(0, 10000000000000000))
    print('Random seed selected: {}'.format(seed))

    # Generate trento event
    trentoDataframe, trentoOutputFile, trentoSubprocess = hic.runTrento(projectile1='Pb', projectile2='Pb',
                                                                        outputFile=True, randomSeed=seed,
                                                                        normalization=18.1175, crossSection=7.0,
                                                                        quiet=False, filename=temp_dir.name + '/initial.hdf')

    # Format trento data into initial conditions for freestream
    print('Packaging trento initial conditions into array...')
    ic = hic.toFsIc(initial_file='initial.hdf', quiet=False)

    #################
    # Freestreaming #
    #################
    # Freestream initial conditions
    print('Freestreaming Trento conditions...')
    fs = freestream.FreeStreamer(initial=ic, grid_max=grid_max, time=config.TAU_FS)

    # Important to close the hdf5 file.
    del ic

    #########
    # Hydro #
    #########
    # Run hydro on initial conditions
    # This is where we control the end point of the hydro. The HRG object created here has an energy density param.
    # that we use as the cut-off energy density for the hydro evolution. Doing things through frzout.HRG allows us to
    # specify a minimum temperature that will be enforced with the energy density popped out here.
    # create sampler HRG object (to be reused for all events)
    hrg_kwargs = dict(species='urqmd', res_width=True)
    hrg = frzout.HRG(config.T_END, **hrg_kwargs)

    # append switching energy density to hydro arguments
    eswitch = hrg.energy_density()
    hydro_args = ['edec={}'.format(eswitch)]

    # Coarse run to determine maximum radius
    print('Running coarse hydro...')
    coarseHydroDict = hic.run_hydro(fs, event_size=27, coarse=3, grid_step=config.GRID_STEP, tau_fs=config.TAU_FS,
                                    hydro_args=hydro_args)
    rmax = math.sqrt((
                             coarseHydroDict['x'][:, 1:3] ** 2
                     ).sum(axis=1).max())
    logging.info('rmax = %.3f fm', rmax)

    # Fine run
    print('Running fine hydro...')
    hic.run_hydro(fs, event_size=rmax, grid_step=config.GRID_STEP, tau_fs=config.TAU_FS, hydro_args=hydro_args)

    ########################
    # Objectify Background #
    ########################
    # Create plasma object
    # Open the hydro file and create file object for manipulation.
    plasmaFilePath = 'viscous_14_moments_evo.dat'
    current_file = plasma.osu_hydro_file(file_path=plasmaFilePath, event_name=seed)

    # Create event object
    # This asks the hydro file object to interpolate the relevant functions and pass them on to the plasma object.
    current_event = plasma.plasma_event(event=current_file)

    ################
    # Jet Analysis #
    ################
    # Oversample the background with jets
    for jetNo in range(0, config.NUM_SAMPLES):

        # Select jet production point
        if not config.VARY_POINT:
            x0 = 0
            y0 = 0
        else:
            newPoint = hic.generate_jet_point(current_event)
            x0, y0 = newPoint[0], newPoint[1]

        # Select jet production angle
        theta0 = np.random.uniform(0, 2 * np.pi)

        # Generate jet object
        current_jet = jets.jet(x0=x0, y0=y0,
                               theta0=theta0, event=current_event, energy=config.JET_ENERGY)

        # Sample for shower correction
        # Currently just zero
        shower_correction = 0

        # Calculate momentPlasma
        print('Unhydrodynamic Moment:')
        momentUnhydro, momentUnhydroErr = pi.moment_integral(event=current_event, jet=current_jet, k=config.K,
                                                             minTemp=0, maxTemp=config.T_UNHYDRO)
        print('Hadron Gas Moment:')
        momentHrg, momentHrgErr = pi.moment_integral(event=current_event, jet=current_jet, k=config.K,
                                                     minTemp=config.T_UNHYDRO, maxTemp=config.T_HRG)
        print('Plasma Moment:')
        momentPlasma, momentPlasmaErr = pi.moment_integral(event=current_event, jet=current_jet, k=config.K,
                                                           minTemp=config.T_HRG)

        # Calculate deflection angle
        # Basic trig with k=0.
        if config.K == 0:
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
                    "pT_plasma_error": [momentPlasmaErr],
                    "pT_hrg": [momentHrg],
                    "pT_hrg_error": [momentHrgErr],
                    "pT_unhydro": [momentUnhydro],
                    "pT_unhydro_error": [momentUnhydroErr],
                    "k_moment": [config.K],
                    "deflection_angle_plasma": [deflection_angle_plasma],
                    "deflection_angle_plasma_error": [deflection_angle_plasma_error],
                    "deflection_angle_hrg": [deflection_angle_hrg],
                    "deflection_angle_hrg_error": [deflection_angle_hrg_error],
                    "deflection_angle_unhydro": [deflection_angle_unhydro],
                    "deflection_angle_unhydro_error": [deflection_angle_unhydro_error],
                    "shower_correction": [shower_correction],
                    "X0": [x0],
                    "Y0": [y0],
                    "theta0": [theta0],
                }
            )

        # Merge the trento and momentPlasma dataframes
        currentResultDataframe = pd.concat([momentDataframe, trentoDataframe], axis=1)
        # Append current result step to dataframe
        resultsDataframe = resultsDataframe.append(currentResultDataframe)

        # Declare jet complete
        print('Jet ' + str(jetNo) + ' Complete')

    ################
    # Save Results & Clean-Up#
    ################
    # Save dataframe
    if os.path.exists('../results'):
        print('Making results directory...')
        pass
    else:
        os.mkdir('../results')

    print('Saving progress...')
    resultsDataFrame.to_pickle('../results/' + str(resultsFile) + '.pkl')  # Save dataframe to pickle

    # Delete all event files
    # clear everything in the temporary directory and delete it.
    print('Cleaning temporary directory (dumping event data)...')
    temp_dir.cleanup()

# Setting to loop until stopped???
